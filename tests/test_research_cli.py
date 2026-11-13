# Proposed fixture: pending owner review (the stand-in agents and the scripted command agent are
# written by Claude).
"""The command line and the stdio server, end to end on the constructed corpus."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.evidence import AuditReport
from isitright.packs.research.agents import ResearchTask
from isitright.packs.research.audit import AuditConfig, ResearchAudit
from isitright.packs.research.retrieval import FrozenStats
from isitright.packs.research.runs import read_run

from .research_fixtures import ROOT, corpus, task

runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, ["research", *args])


def base_args(out: Path) -> list[str]:
    return [
        "check",
        str(ROOT / "corpus"),
        "--task",
        str(ROOT / "task.json"),
        "--output",
        str(out),
    ]


def test_check_writes_report_artifacts_cases_and_exports(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = invoke(*base_args(out), "--stand-in", "credulous", "--depth", "1")
    assert result.exit_code == 0, result.output
    assert "Counterexample found" in result.output
    report = AuditReport.model_validate_json((out / "report.json").read_text(encoding="utf-8"))
    assert report.schema_version == "0.8" and report.pack == "research"
    case = report.cases[0]
    assert case.findings[0].replay.artifact == "1.replay.json"
    assert case.findings[0].replay.artifact_sha256
    assert "Proposed classification (by the implementing assistant, not a verdict)" in (
        out / "findings-cases.md"
    ).read_text(encoding="utf-8")
    replayed = invoke("replay", str(out / "1.replay.json"))
    assert replayed.exit_code == 0 and "Reproduced." in replayed.output
    exported = tmp_path / "cases"
    done = invoke("export", str(out / "report.json"), "--output", str(exported))
    assert done.exit_code == 0 and "eval case(s) exported" in done.output
    first = json.loads((exported / "1.eval-case.json").read_text(encoding="utf-8"))
    assert first["pack"] == "research" and first["payload"]["question"] == task().question
    # the export from disk equals the one written at audit time
    assert first == json.loads((out / "1.eval-case.json").read_text(encoding="utf-8"))


def test_fail_on_gives_a_distinct_exit_code(tmp_path: Path) -> None:
    result = invoke(
        *base_args(tmp_path / "a"),
        "--stand-in",
        "credulous",
        "--depth",
        "1",
        "--fail-on",
        "domain-counterexample",
    )
    assert result.exit_code == 3
    careful = invoke(
        *base_args(tmp_path / "b"),
        "--stand-in",
        "careful",
        "--depth",
        "1",
        "--fail-on",
        "any-counterexample",
    )
    assert careful.exit_code == 0 and "Not found within budget" in careful.output


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ([], "Choose exactly one of"),
        (["--stand-in", "careful", "--agent", "x:y"], "Choose exactly one of"),
        (["--agent", "x:y"], "pass --trust-code"),
        (["--agent-command", "echo"], "pass --trust-code"),
        (["--stand-in", "nope"], "unknown stand-in 'nope'"),
        (["--agent", "no_such_module_xyz:agent", "--trust-code"], "cannot load agent"),
        (["--agent", "plain", "--trust-code"], "agent reference looks like module:attr"),
    ],
)
def test_input_errors_have_exit_code_two_and_a_message(
    tmp_path: Path, extra: list[str], message: str
) -> None:
    result = invoke(*base_args(tmp_path / "o"), *extra)
    assert result.exit_code == 2 and message in result.output


def test_output_directory_must_be_new(tmp_path: Path) -> None:
    (tmp_path / "o").mkdir()
    result = invoke(*base_args(tmp_path / "o"), "--stand-in", "careful")
    assert result.exit_code == 2 and "already exists" in result.output


def test_a_money_budget_is_refused_for_an_agent_that_reports_no_cost(tmp_path: Path) -> None:
    result = invoke(*base_args(tmp_path / "o"), "--stand-in", "careful", "--max-money", "1")
    assert result.exit_code == 2
    assert "a money budget needs an agent that reports its cost" in result.output


def test_record_runs_and_frozen_replay_of_the_recorded_run(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    first = invoke(
        *base_args(tmp_path / "live"),
        "--stand-in",
        "careful",
        "--depth",
        "1",
        "--record-runs",
        str(runs),
    )
    assert first.exit_code == 0
    recorded = read_run(runs / "baseline-1.json")
    assert recorded.subject.name == "careful" and recorded.report.answer == "1962"
    frozen = invoke(
        *base_args(tmp_path / "frozen"), "--recorded-run", str(runs / "baseline-1.json")
    )
    assert frozen.exit_code == 0, frozen.output
    report = AuditReport.model_validate_json(
        (tmp_path / "frozen" / "report.json").read_text(encoding="utf-8")
    )
    case = report.cases[0]
    assert case.subject_kind == "FROZEN_ARTIFACT"
    ext = case.extensions["research"]
    assert ext["mode"] == "frozen" and "report is not regenerated" in ext["subject_statement"]
    assert case.controls is not None and case.controls.status == "NOT_APPLICABLE"
    assert all(f.mode == "frozen_trace" for f in case.findings)


def test_agent_given_as_code_runs_in_process(tmp_path: Path) -> None:
    agent_file = tmp_path / "my_agent.py"
    agent_file.write_text(
        "from isitright.packs.research.agents import Credulous\n"
        "def make(task):\n    return Credulous()\n",
        encoding="utf-8",
    )
    result = invoke(
        *base_args(tmp_path / "o"), "--agent", f"{agent_file}:make", "--trust-code", "--depth", "1"
    )
    assert result.exit_code == 0 and "Counterexample found" in result.output


def test_stdio_server_and_agent_command_end_to_end(tmp_path: Path) -> None:
    """A real MCP connection: the agent command starts the research server from mcp.json, calls
    only search and open, and writes report.json. The careful scripted agent is not flagged and
    the credulous one is, as in process."""
    pytest.importorskip("mcp")
    command = f'"{sys.executable}" "{ROOT / "command_agent.py"}" --task "{ROOT / "task.json"}"'
    out = tmp_path / "careful"
    result = invoke(
        *base_args(out),
        "--agent-command",
        f"{command} --mode careful {{mcp_config}} {{run_dir}}",
        "--trust-code",
        "--depth",
        "1",
        "--attempts",
        "6",
        "--no-minimize",
        "--timeout",
        "120",
    )
    assert result.exit_code == 0, result.output
    report = AuditReport.model_validate_json((out / "report.json").read_text(encoding="utf-8"))
    ext = report.cases[0].extensions["research"]
    assert ext["subject"]["kind"] == "live_agent"
    assert ext["baseline"]["reports"][0]["answer"] == "1962"
    assert ext["baseline"]["queries"] and ext["baseline"]["opened"]
    assert report.cases[0].worlds, "worlds were run through the server"


def test_the_server_serves_two_tools_and_refuses_the_rest(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.client.stdio import StdioServerParameters

    from isitright.core.mutations import World
    from isitright.packs.mcp.session import McpSession
    from isitright.packs.research.documents import COLLECTION

    stats = FrozenStats.from_documents(corpus().entities(COLLECTION))
    (tmp_path / "world.json").write_text(json.dumps(World(corpus()).to_json()), encoding="utf-8")
    (tmp_path / "stats.json").write_text(json.dumps(stats.to_json()), encoding="utf-8")
    session = McpSession(
        StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "isitright.packs.research.serve",
                "--world-file",
                str(tmp_path / "world.json"),
                "--stats-file",
                str(tmp_path / "stats.json"),
                "--run-dir",
                str(tmp_path),
            ],
        )
    )
    try:
        assert sorted(t.name for t in session.list_tools()) == ["open", "search"]
        found = session.call_tool("search", {"query": "Halvorsen Bridge completed", "k": 2})
        assert not found.is_error and json.loads(found.text)["results"][0]["id"].startswith(
            "bridge-halvorsen"
        )
        bad = session.call_tool("fetch", {"url": "http://example.com"})
        assert bad.is_error
        refused = session.call_tool("open", {"id": "../../etc/passwd"})
        assert refused.is_error and "no document with id" in refused.text
    finally:
        session.close()
    trace = [json.loads(x) for x in (tmp_path / "trace.jsonl").read_text("utf-8").splitlines()]
    assert [e["name"] for e in trace] == ["search", "fetch", "open"]
    assert [e["is_error"] for e in trace] == [False, True, True]


def test_config_defaults_are_the_documented_ones() -> None:
    c = AuditConfig()
    assert (c.attempts, c.depth, c.sequential, c.max_pairs) == (500, 2, True, 16)
    assert isinstance(ResearchAudit(corpus(), task(), c).task, ResearchTask)
