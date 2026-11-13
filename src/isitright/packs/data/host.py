"""The data host: run programs on worlds in a separate, limited process.

Each run gets a fresh temporary directory holding the world's files, a scrubbed environment, a
wall-clock timeout and a memory limit. The program never runs in the audit process, and never
without ``trust_code=True``.

How the memory limit is enforced (``memory_enforcement()``):

* Windows: a Job Object caps the memory the runner may commit; an allocation over the limit fails
  with ``MemoryError``. Exact.
* Linux and macOS with ``psutil`` installed: a watchdog thread in this process reads the resident
  memory of the runner and its children every ``WATCH_INTERVAL`` seconds and kills the process
  group above the limit; inside the runner a thread watches its own peak resident memory as a
  second line. Approximate: a program can pass the limit between two readings (measured overshoot
  in ``docs/data.md``).
* Linux without ``psutil``: an address-space limit (``RLIMIT_AS``), which counts reserved virtual
  memory, so NumPy or pandas can hit it far below their real use.
* macOS without ``psutil``: none (macOS has no ``RLIMIT_AS``); a warning says so.

By default every run starts a new process (``reuse=1``). ``reuse=N`` keeps a process for N runs:
modules a program imported stay loaded, so one run can affect the next, but a run takes
milliseconds instead of seconds. A process is replaced after a timeout, a crash or N runs, and a
report states which was used.

This is **not a security boundary.** Network and file access are blocked by an in-process audit
hook that catches ordinary Python code; native extensions and ``ctypes`` get around it, and
nothing limits CPU use other than the timeout. Run audits of untrusted programs in a container
or VM without network access.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from isitright.core.entities import EntitySchema
from isitright.core.hosts import Fidelity
from isitright.core.world import State
from isitright.packs.data.mapping import write_state

RUNNER = Path(__file__).with_name("_runner.py")
MAX_CAPTURE = 64 * 1024
WATCH_INTERVAL = 0.05
"""Seconds between two readings of the runner's resident memory by the watchdog."""
MEMORY_MARK = "isitright runner: memory limit exceeded"
"""The line the runner writes to stderr before it ends itself over the limit (``_runner.py``)."""
MB = 1024 * 1024


def memory_enforcement(platform: str | None = None, *, psutil_available: bool | None = None) -> str:
    """How a memory limit is enforced on ``platform`` (default: this one): ``job_object``,
    ``rss_watchdog``, ``address_space`` or ``none``. See the module docstring."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return "job_object"
    if psutil_available is None:
        psutil_available = importlib.util.find_spec("psutil") is not None
    if psutil_available:
        return "rss_watchdog"
    return "none" if platform == "darwin" else "address_space"


def _kill_group(pid: int) -> None:
    if sys.platform == "win32":  # pragma: no cover - the Job Object ends the tree there
        return
    import signal

    with suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pid, signal.SIGKILL)


class _Watchdog:
    """Kills the runner's process group when the resident memory of the runner and its children
    passes the limit. Reads it every ``interval`` seconds, so a fast allocation can pass the limit
    by what it allocates between two readings. Needs ``psutil``; POSIX only."""

    def __init__(self, pid: int, limit: int, interval: float = WATCH_INTERVAL) -> None:
        import psutil

        self.limit = limit
        self.interval = interval
        self.exceeded: int | None = None
        """The resident memory read when the limit was passed (bytes): a lower bound of the peak."""
        self._psutil = psutil
        self._process = psutil.Process(pid)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="isitright-watchdog", daemon=True)
        self._thread.start()

    def resident(self) -> int | None:
        """Bytes resident in the runner and its children, or None once the runner is gone."""
        try:
            processes = [self._process, *self._process.children(recursive=True)]
        except self._psutil.Error:
            return None
        total = 0
        for process in processes:
            with suppress(self._psutil.Error):
                total += int(process.memory_info().rss)
        return total

    def _watch(self) -> None:
        while not self._stop.is_set():
            resident = self.resident()
            if resident is None:
                return
            if resident > self.limit:
                self.exceeded = resident
                _kill_group(self._process.pid)
                return
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


class UntrustedCodeError(RuntimeError):
    """A program was about to run without an explicit opt-in."""


@dataclass
class RunResult:
    """What one execution produced. ``status`` is ok, error, timeout, memory or unsupported."""

    status: str
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    final_answer: Any = None
    has_final_answer: bool = False
    result: Any = None
    result_name: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def answer(self) -> tuple[Any, str]:
        """The program's answer and where it came from: ``final_answer``, ``result`` or stdout."""
        if self.has_final_answer:
            return self.final_answer, "final_answer"
        if self.result_name is not None:
            return self.result, self.result_name
        if self.stdout.strip():
            return self.stdout.strip(), "stdout"
        return None, "none"


def scrubbed_environment(home: Path) -> dict[str, str]:
    """Only what the interpreter needs. No API keys or other inherited variables."""
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TEMP": str(home),
        "TMP": str(home),
        "TMPDIR": str(home),
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "MPLBACKEND": "Agg",
        "OMP_NUM_THREADS": "1",
    }
    for name in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "LANG", "LC_ALL"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


class _Limits:
    """Platform-specific containment of the child process."""

    def __init__(self, memory_bytes: int | None, enforcement: str) -> None:
        self.memory_bytes = memory_bytes
        self.enforcement = enforcement
        self.job: Any = None

    def preexec(self) -> Any:
        if sys.platform == "win32" or not self.memory_bytes:
            return None
        if self.enforcement == "none":
            # macOS does not support RLIMIT_AS (setrlimit fails in the child and the process never
            # starts), and without psutil there is no watchdog. The time limit still applies.
            warnings.warn(
                "the memory limit is not enforced on macOS without psutil (no RLIMIT_AS); install "
                "isitright[data] or psutil. The timeout still is",
                RuntimeWarning,
                stacklevel=2,
            )
            return None
        if self.enforcement != "address_space":
            return None  # the watchdog enforces it from outside
        import resource

        limit = self.memory_bytes

        def apply() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        return apply

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        if sys.platform != "win32":
            return
        from isitright.packs.data import _winjob

        self.job = _winjob.assign(process, self.memory_bytes)

    def release(self) -> None:
        if self.job is not None:
            from isitright.packs.data import _winjob

            _winjob.close(self.job)
            self.job = None


class _Worker:
    """One runner process: requests go in as JSON lines, replies come back the same way."""

    def __init__(self, memory_bytes: int | None, enforcement: str) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="isitright-worker-"))
        self.limits = _Limits(memory_bytes, enforcement)
        self.watchdog: _Watchdog | None = None
        self.runs = 0
        self._stderr: IO[bytes] = open(self.home / "stderr.txt", "wb")  # noqa: SIM115
        popen: dict[str, Any] = {}
        env = scrubbed_environment(self.home)
        if memory_bytes and enforcement in ("job_object", "rss_watchdog"):
            # The runner applies it to itself: on Windows it joins a Job Object, on POSIX it starts
            # its own check, the second line behind the watchdog (see _runner._limit_memory)
            env["ISITRIGHT_MEMORY_BYTES"] = str(memory_bytes)
        if sys.platform == "win32":
            popen["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            popen["preexec_fn"] = self.limits.preexec()
            popen["start_new_session"] = True
        self.process = subprocess.Popen(
            [sys.executable, "-s", "-B", str(RUNNER)],
            cwd=self.home,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            **popen,
        )
        self.limits.attach(self.process)
        if memory_bytes and enforcement == "rss_watchdog":
            self.watchdog = _Watchdog(self.process.pid, memory_bytes)
        self._lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            self._lines.put(line)
        self._lines.put(b"")

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def request(self, payload: Mapping[str, Any], timeout: float) -> dict[str, Any] | None:
        """The reply, or None if the process timed out or died (it is closed in both cases)."""
        assert self.process.stdin is not None
        self.runs += 1
        try:
            self.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            line = self._lines.get(timeout=timeout)
        except (queue.Empty, BrokenPipeError, OSError):
            self.close()
            return None
        if not line:
            self.close()
            return None
        reply: dict[str, Any] = json.loads(line)
        return reply

    def stderr_tail(self) -> str:
        with suppress(OSError, ValueError):
            return (self.home / "stderr.txt").read_text(encoding="utf-8", errors="replace")[-400:]
        return ""

    def close(self) -> None:
        if self.watchdog is not None:
            self.watchdog.stop()
        self.limits.release()  # a Job Object closes the whole process tree
        with suppress(ProcessLookupError, PermissionError, OSError):
            if self.process.poll() is None:
                if sys.platform == "win32":
                    self.process.kill()
                else:
                    _kill_group(self.process.pid)
        with suppress(OSError):
            self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self._stderr):
            with suppress(OSError, ValueError):
                if stream is not None:
                    stream.close()

    def dispose(self) -> None:
        self.close()
        for _ in range(5):
            shutil.rmtree(self.home, ignore_errors=True)
            if not self.home.exists():
                break
            time.sleep(0.1)


class DataHost:
    """Runs programs on worlds. ``fidelity`` is NATIVE_ISOLATED: the real interpreter and libraries
    in a separate process, whose versions each result reports."""

    fidelity = Fidelity.NATIVE_ISOLATED

    def __init__(
        self,
        schema: EntitySchema,
        *,
        trust_code: bool = False,
        timeout_seconds: float = 30.0,
        memory_mb: int | None = 2048,
        outputs: tuple[str, ...] = (),
        data_format: str = "csv",
        reuse: int = 1,
    ) -> None:
        self.schema = schema
        self.trust_code = trust_code
        self.timeout_seconds = timeout_seconds
        self.memory_bytes = memory_mb * MB if memory_mb else None
        self.enforcement = memory_enforcement() if self.memory_bytes else "none"
        self.outputs = outputs
        self.data_format = data_format
        self.reuse = max(1, reuse)
        self._local = threading.local()
        self._workers: list[_Worker] = []
        self._lock = threading.Lock()

    def describe(self) -> dict[str, Any]:
        return {
            "isolation": "process per run"
            if self.reuse == 1
            else f"process reused for {self.reuse} runs",
            "timeout_seconds": self.timeout_seconds,
            "memory_limit_mb": self.memory_bytes // MB if self.memory_bytes else None,
            "memory_enforcement": self.enforcement,
            "data_format": self.data_format,
        }

    def close(self) -> None:
        with self._lock:
            workers, self._workers = self._workers, []
        for worker in workers:
            worker.dispose()

    def _worker(self) -> _Worker:
        worker: _Worker | None = getattr(self._local, "worker", None)
        if worker is not None and worker.alive and worker.runs < self.reuse:
            return worker
        if worker is not None:
            with self._lock:
                if worker in self._workers:
                    self._workers.remove(worker)
            worker.dispose()
        worker = _Worker(self.memory_bytes, self.enforcement)
        with self._lock:
            self._workers.append(worker)
        self._local.worker = worker
        return worker

    def run(self, code: str, state: State) -> RunResult:
        """Run ``code`` on a world: its files are written to a fresh directory first."""
        self._need_trust()
        root = Path(tempfile.mkdtemp(prefix="isitright-data-"))
        try:
            work = root / "work"
            write_state(state, self.schema, work, self.data_format)
            return self._run_in(code, work)
        finally:
            for _ in range(5):
                shutil.rmtree(root, ignore_errors=True)
                if not root.exists():
                    break
                time.sleep(0.1)

    def run_directory(self, code: str, directory: Path) -> RunResult:
        """Run ``code`` with ``directory`` as its working directory (a stand-in agent's tool)."""
        self._need_trust()
        return self._run_in(code, directory)

    def _need_trust(self) -> None:
        if not self.trust_code:
            raise UntrustedCodeError(
                "refusing to run a recorded program without trust_code=True (--trust-code): "
                "its code runs on this machine"
            )

    def _run_in(self, code: str, work: Path) -> RunResult:
        started = time.monotonic()
        worker = self._worker()
        reply = worker.request(
            {"code": code, "work": str(work), "outputs": list(self.outputs)}, self.timeout_seconds
        )
        seconds = time.monotonic() - started
        if reply is None:
            return self._lost(worker, seconds)
        return self._result(reply, seconds)

    def _lost(self, worker: _Worker, seconds: float) -> RunResult:
        stderr = worker.stderr_tail()
        if seconds >= self.timeout_seconds:
            return RunResult(
                "timeout", stderr=stderr, error=f"over {self.timeout_seconds:g} s", seconds=seconds
            )
        watched = worker.watchdog.exceeded if worker.watchdog is not None else None
        memory = self.memory_bytes is not None and (
            watched is not None or "MemoryError" in stderr or MEMORY_MARK in stderr
        )
        error = "the process ended without a reply"
        if watched is not None and self.memory_bytes:
            error += (
                f" (memory limit: {watched // MB} MB resident, over the "
                f"{self.memory_bytes // MB} MB limit; stopped by the watchdog)"
            )
        elif memory:
            error += " (memory limit)"
        return RunResult(
            "memory" if memory else "error", stderr=stderr, error=error, seconds=seconds
        )

    @staticmethod
    def _result(data: Mapping[str, Any], seconds: float) -> RunResult:
        violations = list(data.get("violations", []))
        # A blocked operation makes the run unsupported only if the program failed on it; a library
        # that probes (a CPU count, a platform lookup) and carries on is recorded, not rejected.
        status = str(data["status"])
        if violations and status != "ok":
            status = "unsupported"
        if status == "error" and "MemoryError" in str(data.get("error", "")):
            status = "memory"
        return RunResult(
            status,
            str(data.get("stdout", "")),
            str(data.get("stderr", "")),
            str(data.get("error", "")),
            data.get("final_answer"),
            bool(data.get("has_final_answer")),
            data.get("result"),
            data.get("result_name"),
            dict(data.get("outputs", {})),
            dict(data.get("versions", {})),
            violations,
            seconds,
        )
