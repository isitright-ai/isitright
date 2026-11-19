"""P2: a report can be moved, and its replay command still works.

A reviewer who downloads a CI artifact opens the report on another machine. Nothing a report, a
replay artifact or a printed hint says may name the directory the audit wrote to, and the replay
command a report prints must work from any directory once the reader says where the file now is.
Each report prints its command with a placeholder in angle brackets, named after the file
(``<report.json>``); the reader replaces it with the file's location.

For every pack: write a report, copy the whole output directory to a different parent, delete the
original, substitute the placeholder, and run the command from a third directory. The leak check
covers every text file isitright wrote, the run directories of the agents pack included; the only
exception is ``agent.log``, which is whatever the agent printed.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from isitright import check
from isitright.cli import app
from isitright.packs.sql.reports import write_case_report

runner = CliRunner()
PLACEHOLDER = re.compile(r"<([^<>\s]+)>")
TEXT_SUFFIXES = {".json", ".md", ".jsonl", ".txt", ".sql"}


def _spellings(directory: Path) -> set[str]:
    resolved = directory.resolve()
    return {
        str(directory),
        str(resolved),
        resolved.as_posix(),
        str(resolved).replace("\\", "\\\\"),  # the way json.dumps writes a Windows path
    }


def _assert_no_leak(moved: Path, original: Path, stdout: str) -> None:
    needles = _spellings(original)
    texts = {"<stdout>": stdout}
    for path in moved.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES and path.name != "agent.log":
            texts[str(path.relative_to(moved))] = path.read_text(encoding="utf-8", errors="replace")
    leaks = [name for name, text in texts.items() if any(n in text for n in needles)]
    assert not leaks, f"the original directory is named in: {leaks}"


def _command_from(report: Path) -> str:
    data = json.loads(report.read_text("utf-8"))
    case = data["cases"][0] if "cases" in data else data
    command = case["findings"][0]["replay"]["command"]
    assert command, "the report prints no replay command"
    return str(command)


def _tokens(command: str, moved: Path) -> list[str]:
    import shlex

    found = PLACEHOLDER.findall(command)
    assert len(found) == 1, f"one placeholder expected in {command!r}"
    target = next(moved.rglob(found[0]))  # the file the placeholder is named after
    command = command.replace(f"<{found[0]}>", f'"{target}"')
    parts = shlex.split(command, posix=False)
    assert parts[0] == "isitright", command
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts[1:]]


def _move_and_replay(
    original: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report_name: str
) -> tuple[Any, Path]:
    moved = tmp_path / "somewhere else entirely" / "moved"
    moved.parent.mkdir()
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    command = _command_from(moved / report_name)
    third = tmp_path / "third"
    third.mkdir()
    monkeypatch.chdir(third)
    return runner.invoke(app, _tokens(command, moved)), moved


def test_sql_report_survives_a_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT NOT NULL);")
        connection.executemany("INSERT INTO t(v) VALUES (?)", [("a",), ("a",), ("b",)])
    result = check(
        database=database, reference_sql="SELECT v FROM t", candidate_sql="SELECT DISTINCT v FROM t"
    )
    original = tmp_path / "original-location-sql" / "out"
    write_case_report(result, original)
    done, moved = _move_and_replay(original.parent, tmp_path, monkeypatch, "out/case_report.json")
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output
    _assert_no_leak(moved, original.parent, done.output)


@pytest.fixture
def data_original(tmp_path: Path) -> Path:
    pytest.importorskip("pandas")
    from isitright.packs.data.programs import write_programs
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    task = make_task(tmp_path / "orders")
    programs = tmp_path / "programs.jsonl"
    write_programs(programs, [program(DROPNA_FORGOTTEN, "mistake")])
    out = tmp_path / "original-location-data" / "out"
    args = ["data", "check", str(task), "--programs", str(programs), "--output", str(out)]
    made = runner.invoke(app, [*args, "--trust-code", "--attempts", "60", "--reuse", "20"])
    assert made.exit_code == 0, made.output
    return out


def test_data_report_survives_a_move(
    data_original: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done, moved = _move_and_replay(data_original.parent, tmp_path, monkeypatch, "out/report.json")
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output
    _assert_no_leak(moved, data_original.parent, done.output)


def test_research_report_survives_a_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.research_fixtures import ROOT

    out = tmp_path / "original-location-research" / "out"
    args = ["research", "check", str(ROOT / "corpus"), "--task", str(ROOT / "task.json")]
    made = runner.invoke(
        app, [*args, "--output", str(out), "--stand-in", "credulous", "--depth", "1"]
    )
    assert made.exit_code == 0, made.output
    done, moved = _move_and_replay(out.parent, tmp_path, monkeypatch, "out/report.json")
    assert done.exit_code == 0, done.output
    assert "Reproduced" in done.output
    _assert_no_leak(moved, out.parent, done.output)


def test_agents_report_survives_a_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from isitright.packs.mcp.audit import run_scenario

    examples = Path(__file__).parents[1] / "examples" / "agents"
    out = tmp_path / "original-location-agents" / "out"
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
    done, moved = _move_and_replay(out.parent, tmp_path, monkeypatch, "out/report.json")
    assert done.exit_code == 0, done.output
    assert "reproduced" in done.output and "NOT reproduced" not in done.output
    _assert_no_leak(moved, out.parent, done.output)
