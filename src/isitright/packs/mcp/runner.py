"""Start an agent command against one served world and read back what it left.

The agent is any command that accepts an MCP configuration. For each run the runner creates a run
directory, writes ``mcp.json`` (the standard ``mcpServers`` format) pointing at
``python -m isitright.packs.mcp.serve`` for that world, writes ``task.txt``, and starts the command
with ``{mcp_config}``, ``{task_file}`` and ``{run_dir}`` substituted into its arguments and exported
as ``ISITRIGHT_MCP_CONFIG``, ``ISITRIGHT_TASK_FILE`` and ``ISITRIGHT_RUN_DIR``. The agent's own MCP
client launches the server, so the server process owns the state and writes the files read here.
Process-tree kill on timeout is preserved from the earlier runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isitright.core.subjects import Cost, RunRecord, RunStatus
from isitright.packs.mcp.model import ServiceState, TraceDict

KILL_GRACE_SECONDS = 10


class AgentsInputError(ValueError):
    """The request cannot be run: missing consent, missing dependency or an unusable command."""


def split_command(command: str) -> list[str]:
    tokens = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        tokens = [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t for t in tokens]
    if not tokens:
        raise AgentsInputError("the agent command is empty")
    if "/" in tokens[0]:
        # Windows cannot start a relative executable written with forward slashes.
        tokens[0] = os.path.normpath(tokens[0])
    return tokens


def harness_identity(argv: list[str]) -> tuple[str | None, str | None]:
    """Name and content-hash version of the agent program, if the command runs a ``.py`` file."""
    for token in argv[1:]:
        path = Path(token)
        if token.endswith(".py") and path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            return path.stem, f"sha256:{digest}"
    return None, None


def read_transcript(run_dir: Path, harness: tuple[str | None, str | None]) -> dict[str, Any]:
    """What the agent's ``transcript.json`` says about the stack under test and its usage.

    Absent or unreadable transcripts give an empty result: not every agent writes one, and a
    crashed agent may leave none. ``cost`` in a usage entry is the money that call used, in the
    agent's own unit (simulated for scripted agents).
    """
    path = run_dir / "transcript.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        subject = {
            "provider": str(data["provider"]),
            "model": str(data["model"]),
            "harness_name": harness[0],
            "harness_version": harness[1],
            "sdk_versions": {str(k): str(v) for k, v in (data.get("sdk_versions") or {}).items()},
            "settings": dict(data.get("settings") or {}),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    usage = data.get("usage")
    stop = data.get("stop_reason")
    result: dict[str, Any] = {
        "subject": subject,
        "agent_stop_reason": stop if stop in ("final", "max_turns", "error") else None,
    }
    if isinstance(usage, list):
        try:
            result["model_calls"] = len(usage)
            result["input_tokens"] = sum(int(u["input_tokens"]) for u in usage)
            result["output_tokens"] = sum(int(u["output_tokens"]) for u in usage)
        except (KeyError, TypeError, ValueError):
            for key in ("model_calls", "input_tokens", "output_tokens"):
                result.pop(key, None)
        try:
            # Money counts as reported only when every usage entry states its cost.
            result["money"] = float(sum(float(u["cost"]) for u in usage))
        except (KeyError, TypeError, ValueError):
            result.pop("money", None)
    return result


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Stop the agent and everything it started, including its MCP server."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False
        )
    else:  # pragma: no cover - exercised on POSIX runners only
        import signal

        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=KILL_GRACE_SECONDS)


def run_agent(
    argv: list[str],
    run_dir: Path,
    mcp_config: Path,
    task_file: Path,
    world_id: str,
    timeout: float,
) -> tuple[RunStatus, int | None]:
    substitutions = {
        "{mcp_config}": str(mcp_config),
        "{task_file}": str(task_file),
        "{run_dir}": str(run_dir),
    }
    resolved = []
    for token in argv:
        for key, value in substitutions.items():
            token = token.replace(key, value)
        resolved.append(token)
    environment = {
        **os.environ,
        "ISITRIGHT_MCP_CONFIG": str(mcp_config),
        "ISITRIGHT_TASK_FILE": str(task_file),
        "ISITRIGHT_RUN_DIR": str(run_dir),
        "ISITRIGHT_WORLD": world_id,
    }
    with (run_dir / "agent.log").open("wb") as log:
        try:
            process = subprocess.Popen(
                resolved,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=sys.platform != "win32",
            )
        except OSError as error:
            raise AgentsInputError(f"cannot start the agent command: {error}") from error
        try:
            code = process.wait(timeout=timeout)
            return ("COMPLETED" if code == 0 else "SUBJECT_ERROR"), process.returncode
        except subprocess.TimeoutExpired:
            _terminate(process)
            return "TIMEOUT", None


def write_mcp_config(
    run_dir: Path, scenario_ref: str, *, world_file: Path | None, fixed_id: str | None
) -> Path:
    arguments = [
        "-m",
        "isitright.packs.mcp.serve",
        "--scenario",
        scenario_ref,
        *(
            ["--world-file", str(world_file)]
            if world_file is not None
            else ["--fixed", str(fixed_id)]
        ),
        "--run-dir",
        str(run_dir),
        "--trust-code",
    ]
    path = run_dir / "mcp.json"
    path.write_text(
        json.dumps(
            {"mcpServers": {"isitright": {"command": sys.executable, "args": arguments}}}, indent=2
        ),
        encoding="utf-8",
    )
    return path


def read_state(path: Path) -> ServiceState:
    value: ServiceState = json.loads(path.read_text(encoding="utf-8"))
    return value


def read_trace(path: Path) -> list[TraceDict]:
    """Trace rows written by the serving process; a missing file means no tool was called."""
    if not path.is_file():
        return []
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return sorted(events, key=lambda e: int(e["index"]))


@dataclass
class AgentRun:
    """What one agent run left behind, before any judging."""

    record: RunRecord
    before: ServiceState
    after: ServiceState
    trace: list[TraceDict]
    extra: dict[str, Any]


def collect(
    run_dir: Path,
    status: RunStatus,
    duration: float,
    harness: tuple[str | None, str | None],
    fallback_before: ServiceState,
) -> AgentRun:
    before_path = run_dir / "state_before.json"
    before = read_state(before_path) if before_path.is_file() else fallback_before
    after_path = run_dir / "state_after.json"
    after = read_state(after_path) if after_path.is_file() else before
    trace = read_trace(run_dir / "trace.jsonl")
    extra = read_transcript(run_dir, harness)
    cost = Cost(
        input_tokens=int(extra.get("input_tokens", 0)),
        output_tokens=int(extra.get("output_tokens", 0)),
        money=float(extra.get("money", 0.0)),
        seconds=duration,
    )
    record = RunRecord(
        status=status, trace=trace, final_state=after, cost=cost, run_dir=str(run_dir)
    )
    return AgentRun(record, before, after, trace, extra)
