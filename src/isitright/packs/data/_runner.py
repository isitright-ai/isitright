"""The child process that runs untrusted programs. Started by `host.py`, never imported.

Run as ``python -s -B _runner.py``. It reads one JSON request per line on stdin and answers with one
JSON line on the real stdout, running each program in a fresh namespace with the working directory
set to the request's directory. An audit hook blocks network use, process creation, writes outside
the working directory and reads outside it and the Python installation. The hook catches ordinary
Python code; it is not a security boundary (native code and ``ctypes`` bypass it).

The host starts one process per run by default. It can reuse a process for several runs; the
modules a program imports then stay loaded, which is faster and weaker isolation between runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import sysconfig
import traceback
from typing import Any

BLOCKED_EVENTS = {
    "socket.connect": "network access",
    "socket.bind": "network access",
    "socket.getaddrinfo": "network access",
    "socket.gethostbyname": "network access",
    "subprocess.Popen": "starting a process",
    "os.system": "starting a process",
    "os.exec": "starting a process",
    "os.spawn": "starting a process",
    "os.posix_spawn": "starting a process",
    "os.fork": "starting a process",
}
DEVNULLS = {os.path.normcase(os.devnull), "nul", "/dev/null"}
CHANGES_A_PATH = {"os.remove", "os.rename", "os.rmdir", "shutil.rmtree"}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_TRUNC", 0)


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r + os.sep) for r in roots)


class Guard:
    """The audit hook, with the current working directory and the violations of the current run."""

    def __init__(self) -> None:
        self.work = ""
        self.violations: list[str] = []
        self.active = False
        roots = []
        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            value = sysconfig.get_paths().get(key)
            if value:
                roots.append(_real(value))
        for prefix in {
            sys.prefix,
            sys.base_prefix,
            sys.exec_prefix,
            os.path.dirname(sys.executable),
        }:
            roots.append(_real(prefix))
        roots.append(_real(os.path.dirname(__file__)))
        if os.name == "nt":
            roots.append(_real(os.environ.get("SYSTEMROOT", "C:\\Windows")))
        self.read_roots = roots

    def refuse(self, what: str) -> None:
        self.violations.append(what)
        raise PermissionError(f"isitright: {what} is not allowed")

    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        if not self.active:
            return
        if event == "open":
            target, mode, flags = args[0], args[1], args[2]
            if isinstance(target, int) or target is None:
                return
            path = _real(os.fsdecode(target))
            if os.path.normcase(os.fsdecode(target)) in DEVNULLS:
                return  # libraries open the null device to discard output
            writing = bool(flags & WRITE_FLAGS) or any(c in (mode or "") for c in "wax+")
            if writing and not _inside(path, [self.work]):
                self.refuse(f"writing {os.fsdecode(target)!r} outside the working directory")
            if (
                not writing
                and not _inside(path, [self.work, *self.read_roots])
                and os.path.lexists(path)
            ):
                self.refuse(f"reading {os.fsdecode(target)!r} outside the data directory")
            return
        if event in CHANGES_A_PATH:
            targets = [a for a in args[:2] if isinstance(a, str | bytes | os.PathLike)]
            if any(not _inside(_real(os.fsdecode(t)), [self.work]) for t in targets):
                self.refuse(f"changing {os.fsdecode(targets[0])!r} outside the working directory")
            return
        for name, what in BLOCKED_EVENTS.items():
            if event == name or event.startswith(name + "."):
                self.refuse(what)


def _plain(value: Any, depth: int = 0) -> Any:
    """A JSON form of an answer: scalars, lists, mappings, and frames as ``__frame__``."""
    if depth > 6:
        return {"__other__": "nested too deep"}
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else {"__float__": str(value)}
    pandas = sys.modules.get("pandas")
    if pandas is not None:
        if isinstance(value, pandas.DataFrame):
            return {
                "__frame__": {
                    "columns": [str(c) for c in value.columns],
                    "dtypes": [str(t) for t in value.dtypes],
                    "index": [_plain(i, depth + 1) for i in value.index.tolist()],
                    "data": [[_plain(c, depth + 1) for c in row] for row in value.values.tolist()],
                }
            }
        if isinstance(value, pandas.Series):
            return _plain(value.to_frame(), depth + 1)
    item = getattr(value, "item", None)
    if item is not None and getattr(value, "shape", None) == ():
        return _plain(item(), depth + 1)
    tolist = getattr(value, "tolist", None)
    if tolist is not None:
        return _plain(tolist(), depth + 1)
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v, depth + 1) for k, v in value.items()}
    return {"__other__": f"{type(value).__name__}: {value!r}"[:200]}


def _versions() -> dict[str, str]:
    out = {"python": sys.version.split()[0]}
    for name in ("pandas", "numpy", "scipy"):
        module = sys.modules.get(name)
        if module is not None:
            out[name] = str(getattr(module, "__version__", "?"))
    return out


def _reset_libraries() -> None:
    """Undo what one program may have changed in a library the next program also uses."""
    pandas = sys.modules.get("pandas")
    if pandas is not None:
        with contextlib.suppress(Exception):
            pandas.reset_option("all")
    numpy = sys.modules.get("numpy")
    if numpy is not None:
        with contextlib.suppress(Exception):
            numpy.seterr(all="warn")


@contextlib.contextmanager
def _empty_stdin() -> Any:
    original, sys.stdin = sys.stdin, io.StringIO("")
    try:
        yield
    finally:
        sys.stdin = original


def run_one(request: dict[str, Any], guard: Guard) -> dict[str, Any]:
    work = request["work"]
    os.chdir(work)
    guard.work, guard.violations = _real(work), []
    final: list[Any] = []

    def final_answer(value: Any) -> Any:
        final.append(value)
        return value

    namespace: dict[str, Any] = {"__name__": "__main__", "final_answer": final_answer}
    out, err = io.StringIO(), io.StringIO()
    result: dict[str, Any] = {"status": "ok"}
    guard.active = True
    try:
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            _empty_stdin(),
            contextlib.suppress(SystemExit),
        ):
            exec(compile(request["code"], "<program>", "exec"), namespace)
    except BaseException as error:
        lines = traceback.format_exception_only(type(error), error)
        result = {"status": "error", "error": "".join(lines).strip()[-600:]}
    guard.active = False
    result["stdout"] = out.getvalue()[:65536]
    result["stderr"] = err.getvalue()[-4096:]
    if guard.violations:
        result["violations"] = guard.violations
    result["final_answer"] = _plain(final[-1]) if final else None
    result["has_final_answer"] = bool(final)
    for name in ("result", "answer"):
        if name in namespace:
            result["result"] = _plain(namespace[name])
            result["result_name"] = name
            break
    outputs = {}
    pandas = sys.modules.get("pandas")
    for name in request.get("outputs", []):
        path = os.path.join(work, name)
        if os.path.isfile(path) and pandas is not None:
            try:
                outputs[name] = _plain(pandas.read_csv(path))
            except Exception as error:  # an output that is not a readable table
                outputs[name] = {"__other__": f"unreadable: {type(error).__name__}"}
    result["outputs"] = outputs
    result["versions"] = _versions()
    _reset_libraries()
    return result


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    home = os.getcwd()
    requests, replies = sys.stdin, sys.stdout
    guard = Guard()
    sys.addaudithook(guard)
    for line in requests:
        if not line.strip():
            continue
        try:
            reply = run_one(json.loads(line), guard)
        except BaseException as error:
            reply = {"status": "error", "error": f"runner failure: {type(error).__name__}: {error}"}
        replies.write(json.dumps(reply) + "\n")
        replies.flush()
        os.chdir(home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
