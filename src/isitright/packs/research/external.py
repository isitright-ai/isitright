"""Subjects that are not built in: an agent command, an agent given as code, a recorded run.

An *agent command* is any program that can use an MCP server. For each run the audit writes a run
directory with ``world.json`` and ``stats.json``, an ``mcp.json`` that starts
``python -m isitright.packs.research.serve`` on that world, and ``task.txt`` with the question; it
starts the command with ``{mcp_config}``, ``{task_file}`` and ``{run_dir}`` substituted into its
arguments and exported as ``ISITRIGHT_MCP_CONFIG``, ``ISITRIGHT_TASK_FILE`` and
``ISITRIGHT_RUN_DIR``. The agent writes ``report.json`` (a `Report`) into the run directory and may
write ``transcript.json`` (provider, model, usage with token counts and an optional cost). The
serving process writes ``trace.jsonl``. A run without a ``report.json`` is a subject error.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from isitright.core.mutations import World
from isitright.packs.research.agents import Agent, ResearchTask
from isitright.packs.research.audit import Executor, Subject
from isitright.packs.research.retrieval import FrozenStats
from isitright.packs.research.runs import RecordedRun, Report, SubjectLabel


class ExternalError(ValueError):
    """The agent cannot be started or loaded: missing consent, a bad reference or command."""


def load_agent(reference: str, task: ResearchTask) -> Agent:
    """``module:attr`` or ``path/to/file.py:attr``: an object with ``run(tools, task, seed)``, or a
    callable taking the task and returning one. Trusted code: the caller has the consent."""
    if ":" not in reference:
        raise ExternalError("an agent reference looks like module:attr or file.py:attr")
    where, _, attr = reference.rpartition(":")
    try:
        if where.endswith(".py"):
            path = Path(where).resolve()
            sys.path.insert(0, str(path.parent))
            module = importlib.import_module(path.stem)
        else:
            module = importlib.import_module(where)
        target: Any = getattr(module, attr)
    except (ImportError, AttributeError) as error:
        raise ExternalError(f"cannot load agent {reference!r}: {error}") from error
    agent = target if hasattr(target, "run") else target(task)
    if not hasattr(agent, "run") or not hasattr(agent, "label"):
        raise ExternalError(
            f"{reference!r} is not an agent: it needs run(tools, task, seed) and label"
        )
    return agent  # type: ignore[no-any-return]


def command_subject(
    argv: list[str],
    task: ResearchTask,
    stats: FrozenStats,
    *,
    timeout: float,
    name: str = "agent-command",
    work_dir: Path | None = None,
) -> Subject:
    """A subject that runs ``argv`` against the stdio server of each world."""
    from isitright.packs.mcp.runner import harness_identity, read_transcript, run_agent

    root = work_dir or Path(tempfile.mkdtemp(prefix="isitright-research-"))
    counter = {"n": 0}
    harness = harness_identity(argv)
    label = SubjectLabel(
        kind="live_agent",
        name=name,
        written_by="the owner or a vendor (not written by the implementing assistant)",
        note=f"command: {argv[0]}",
    )

    def execute(world: World, seed: int) -> RecordedRun:
        counter["n"] += 1
        run_dir = root / f"run-{counter['n']:04d}"
        run_dir.mkdir(parents=True)
        (run_dir / "world.json").write_text(json.dumps(world.to_json(), sort_keys=True), "utf-8")
        used = stats.restricted(_world_terms(world, task))
        (run_dir / "stats.json").write_text(json.dumps(used.to_json(), sort_keys=True), "utf-8")
        (run_dir / "task.txt").write_text(task.question, encoding="utf-8")
        config = run_dir / "mcp.json"
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "isitright": {
                            "command": sys.executable,
                            "args": [
                                "-m",
                                "isitright.packs.research.serve",
                                "--world-file",
                                str(run_dir / "world.json"),
                                "--stats-file",
                                str(run_dir / "stats.json"),
                                "--run-dir",
                                str(run_dir),
                            ],
                        }
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        started = time.monotonic()
        status, code = run_agent(
            argv, run_dir, config, run_dir / "task.txt", world.fingerprint(), timeout
        )
        trace = _read_trace(run_dir / "trace.jsonl")
        report = Report(answer=None)
        report_path = run_dir / "report.json"
        if status == "COMPLETED":
            try:
                report = Report.model_validate_json(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                status = "SUBJECT_ERROR"
                trace.append(
                    {
                        "index": len(trace),
                        "name": "_agent_error",
                        "arguments": {},
                        "result": f"no usable report.json (exit code {code}): {error}",
                        "is_error": True,
                    }
                )
        extra = read_transcript(run_dir, harness)
        cost = {"seconds": time.monotonic() - started}
        for key in ("input_tokens", "output_tokens", "money"):
            if key in extra:
                cost[key] = float(extra[key])
        return RecordedRun(
            subject=label.model_copy(
                update={"note": f"command: {argv[0]}; {json.dumps(extra.get('subject', {}))}"}
            ),
            task_id=task.id,
            question=task.question,
            trace=trace,
            report=report,
            cost=cost,
            status=status,
            seed=None,
            own_retrieval=_read_own_retrieval(run_dir / "own_retrieval.jsonl"),
        )

    executor: Executor = execute
    return Subject(label, True, executor, reports_cost=False)


def _world_terms(world: World, task: ResearchTask) -> set[str]:
    from isitright.packs.research.documents import COLLECTION
    from isitright.packs.research.retrieval import terms_of, tokenize

    return terms_of(world.state.entities(COLLECTION)) | set(tokenize(task.question))


def _read_own_retrieval(path: Path) -> list[dict[str, Any]]:
    """The searches the agent ran on its own retriever (``own_retrieval.jsonl``: one JSON object
    per line, ``{"query": str, "ids": [str, ...]}``). A line that is not that is dropped."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(row, dict)
            and isinstance(row.get("query"), str)
            and isinstance(row.get("ids"), list)
            and all(isinstance(i, str) for i in row["ids"])
        ):
            rows.append({"query": row["query"], "ids": row["ids"]})
    return rows


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return sorted(rows, key=lambda e: int(e["index"]))
