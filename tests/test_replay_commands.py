"""H4: the replay command a report prints exists, and works from another working directory.

0.8.0 printed ``isitright replay <report>`` for SQL findings (the command is ``isitright sql
replay``), a bare artifact file name for research (it only resolves from the output directory) and
no command at all for the data and agents packs. Artifact paths are stored relative to the report
file, and each printed command names the report or artifact by an absolute path.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from isitright import check
from isitright.cli import app
from isitright.core.paths import quote_for_command
from isitright.packs.sql.reports import write_case_report

runner = CliRunner()


def _tokens(command: str) -> list[str]:
    """Split a printed command the way a shell would, with double quotes only."""
    import shlex

    parts = shlex.split(command, posix=False)
    assert parts[0] == "isitright", command
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts[1:]]


def _run_printed(command: str, cwd: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    other = cwd / "elsewhere"
    other.mkdir(exist_ok=True)
    monkeypatch.chdir(other)
    return runner.invoke(app, _tokens(command))


def _first_command(report: Path) -> tuple[str, dict[str, Any]]:
    data = json.loads(report.read_text("utf-8"))
    case = data["cases"][0] if "cases" in data else data
    finding = case["findings"][0]
    assert finding["replay"]["command"], "the report prints no replay command"
    return finding["replay"]["command"], finding


def test_quote_for_command_quotes_only_what_needs_it() -> None:
    assert quote_for_command("D:\\out\\report.json") == "D:\\out\\report.json"
    assert quote_for_command("/tmp/a b/report.json") == '"/tmp/a b/report.json"'
    assert quote_for_command('a"b c') == '"a\\"b c"'


def test_sql_report_prints_a_command_that_reproduces_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT NOT NULL);")
        connection.executemany("INSERT INTO t(v) VALUES (?)", [("a",), ("a",), ("b",)])
    result = check(
        database=database,
        reference_sql="SELECT v FROM t",
        candidate_sql="SELECT DISTINCT v FROM t",
    )
    out = tmp_path / "artifacts"
    write_case_report(result, out)
    command, finding = _first_command(out / "case_report.json")
    assert command.startswith("isitright sql replay ")
    assert finding["replay"]["artifact"] == "replay.json"  # relative to the report file
    assert (out / finding["replay"]["artifact"]).is_file()
    done = _run_printed(command, tmp_path, monkeypatch)
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output


@pytest.fixture(scope="module")
def data_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("pandas")
    from isitright.packs.data.programs import write_programs
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    root = tmp_path_factory.mktemp("replay-data")
    task = make_task(root / "orders")
    programs = root / "programs.jsonl"
    write_programs(programs, [program(DROPNA_FORGOTTEN, "mistake")])
    out = root / "out"
    args = ["data", "check", str(task), "--programs", str(programs), "--output", str(out)]
    result = runner.invoke(app, [*args, "--trust-code", "--attempts", "60", "--reuse", "20"])
    assert result.exit_code == 0, result.output
    return out


def test_data_report_prints_a_command_that_reproduces_from_another_directory(
    data_out: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "moved away from where it was written"
    shutil.copytree(data_out, out)
    # the report is read where it now lives; the command is rebuilt from the report, so write it
    # again the way a fresh audit would
    from isitright.core.evidence import AuditReport
    from isitright.packs.data.reports import write_report

    report = AuditReport.model_validate_json((out / "report.json").read_text("utf-8"))
    write_report(report, out, {})
    command, finding = _first_command(out / "report.json")
    assert command.startswith("isitright data replay ") and "--trust-code" in command
    assert not Path(finding["replay"]["artifact"]).is_absolute()  # relative to the report file
    markdown = (out / "report.md").read_text("utf-8")
    assert command in markdown
    done = _run_printed(command, tmp_path, monkeypatch)
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output


def test_research_report_prints_a_command_that_reproduces_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.research_fixtures import ROOT

    out = tmp_path / "out"
    args = ["research", "check", str(ROOT / "corpus"), "--task", str(ROOT / "task.json")]
    made = runner.invoke(
        app, [*args, "--output", str(out), "--stand-in", "credulous", "--depth", "1"]
    )
    assert made.exit_code == 0, made.output
    command, finding = _first_command(out / "report.json")
    assert command.startswith("isitright research replay ")
    assert finding["replay"]["artifact"] == "1.replay.json"
    done = _run_printed(command, tmp_path, monkeypatch)
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output


def test_agents_report_prints_a_command_that_reproduces_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isitright.packs.mcp.audit import run_scenario

    examples = Path(__file__).parents[1] / "examples" / "agents"
    out = tmp_path / "out"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", "careless")
        run_scenario(
            scenario_ref=f"{examples / 'booking_scenario.py'}:SCENARIO",
            agent_command=f'"{sys.executable}" "{examples / "demo_agent.py"}"',
            output_dir=out,
            worlds="fixed",
            k=1,
            only=["booked_24h_01m", "flight_cancelled"],
            trust_code=True,
            timeout_seconds=120,
        )
    command, _ = _first_command(out / "report.json")
    assert command.startswith("isitright agents replay ") and "--trust-code" in command
    done = _run_printed(command, tmp_path, monkeypatch)
    assert done.exit_code == 0, done.output
    assert "reproduced" in done.output and "NOT reproduced" not in done.output
