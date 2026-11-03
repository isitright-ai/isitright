"""Recorded programs: the code a data-analysis agent executed, and a static look at it.

A recording is one JSON object per line (``isitright-recorded-program``). The code is replayed on
mutated worlds as a frozen artifact; the answer the agent gave on the original data is kept for
reference only, because the program is run again to get its answer.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FORMAT = "isitright-recorded-program"
VERSION = "0.6"

NETWORK_MODULES = frozenset(
    {"socket", "requests", "urllib", "urllib3", "http", "httpx", "ftplib", "smtplib", "aiohttp"}
)
PROCESS_MODULES = frozenset({"subprocess", "multiprocessing", "pty"})
CLOCK_CALLS = frozenset({"time", "now", "today", "utcnow", "perf_counter", "monotonic"})
RANDOM_MODULES = frozenset({"random", "secrets", "uuid"})
READ_FUNCTIONS = frozenset(
    {"read_csv", "read_parquet", "read_excel", "read_json", "read_table", "read_fwf", "open"}
)
WRITE_FUNCTIONS = frozenset({"to_csv", "to_parquet", "to_excel", "to_json", "savefig", "to_pickle"})


class ProgramSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent", "constructed_stand_in"]
    agent: str = ""
    model: str = ""
    note: str = ""
    library_versions: dict[str, str] = Field(default_factory=dict)
    captured_at: str = ""


class RecordedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["isitright-recorded-program"] = "isitright-recorded-program"
    version: Literal["0.6"] = "0.6"
    task_id: str
    program_id: str
    code: str
    answer: dict[str, Any] = Field(default_factory=dict)
    """What the agent said on the original data: ``text`` and ``source``. Reference only."""
    source: ProgramSource

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.code.encode("utf-8")).hexdigest()[:16]


def load_programs(path: Path) -> list[RecordedProgram]:
    """Read a JSONL file of recordings."""
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(RecordedProgram.model_validate(json.loads(line)))
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
    return out


def write_programs(path: Path, programs: list[RecordedProgram]) -> None:
    path.write_text(
        "".join(json.dumps(p.model_dump(mode="json"), sort_keys=True) + "\n" for p in programs),
        encoding="utf-8",
    )


@dataclass
class Scan:
    """What the static scan found. ``unsupported`` reasons stop the audit; flags are reported."""

    unsupported: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    syntax_error: str | None = None


def _root(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _callee(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def scan_program(code: str, task_files: set[str]) -> Scan:
    """Look for network or process use, reads outside the task's files and nondeterminism.

    The scan is a first filter, not a guarantee: the host runs the program twice on the original
    data and blocks what the audit hook sees. Dynamic file names make a read unverifiable and are
    flagged, not rejected.
    """
    scan = Scan()
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        scan.syntax_error = f"{error.msg} (line {error.lineno})"
        scan.unsupported.append(f"the program does not parse: {scan.syntax_error}")
        return scan
    seeded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                top = module.split(".")[0]
                if top in NETWORK_MODULES:
                    scan.unsupported.append(f"imports {module}: network access")
                elif top in PROCESS_MODULES:
                    scan.unsupported.append(f"imports {module}: starts processes")
                elif top in RANDOM_MODULES:
                    scan.flags.append(f"imports {module}: possibly nondeterministic")
        if not isinstance(node, ast.Call):
            continue
        name = _callee(node)
        if name in {"seed", "default_rng", "RandomState"} or any(
            k.arg == "random_state" for k in node.keywords
        ):
            seeded = True
        if name in CLOCK_CALLS and _root(node.func) in {"time", "datetime", "date", "dt"}:
            scan.flags.append(f"reads the clock ({name})")
        if name in {"sample", "shuffle", "permutation", "choice"} and not any(
            k.arg == "random_state" for k in node.keywords
        ):
            scan.flags.append(f"{name}() without random_state")
        if name in {"system", "popen", "exec", "eval", "__import__"}:
            scan.unsupported.append(f"calls {name}(): runs other code or processes")
        if name in READ_FUNCTIONS | WRITE_FUNCTIONS and node.args:
            target = node.args[0]
            writing = name in WRITE_FUNCTIONS or (
                name == "open"
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and any(c in str(node.args[1].value) for c in "wax+")
            )
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                path = target.value
                escapes = path.startswith(("/", "\\", "~")) or ":" in path or ".." in path
                if escapes:
                    scan.unsupported.append(f"{name}({path!r}) reaches outside the data directory")
                elif not writing:
                    if path in task_files:
                        scan.files_read.append(path)
                    else:
                        scan.unsupported.append(f"{name}({path!r}) reads a file the task lacks")
            elif not writing and name != "open":
                scan.flags.append(f"{name}() with a computed file name")
    if seeded:
        scan.flags = [f for f in scan.flags if "without random_state" not in f]
    return scan
