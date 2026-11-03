"""``isitright data``: check, replay and export through the command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from typer.testing import CliRunner

from isitright.cli import app
from isitright.packs.data.programs import write_programs
from tests.data_factories import CORRECT, DROPNA_FORGOTTEN, make_task, program

runner = CliRunner()


@pytest.fixture(scope="module")
def checked(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("cli")
    task = make_task(root / "orders")
    programs = root / "programs.jsonl"
    write_programs(programs, [program(CORRECT, "correct"), program(DROPNA_FORGOTTEN, "mistake")])
    out = root / "out"
    result = runner.invoke(
        app,
        [
            "data",
            "check",
            str(task),
            "--programs",
            str(programs),
            "--output",
            str(out),
            "--trust-code",
            "--attempts",
            "60",
            "--reuse",
            "20",
        ],
    )
    return result, out, task, programs


def test_check_writes_a_report_with_one_case_per_program(checked) -> None:
    result, out, _, _ = checked
    assert result.exit_code == 0, result.output
    assert "orders:correct: NOT_FOUND_WITHIN_BUDGET" in result.output
    assert "orders:mistake: COUNTEREXAMPLE_FOUND" in result.output
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [c["divergence_status"] for c in report["cases"]] == [
        "NOT_FOUND_WITHIN_BUDGET",
        "COUNTEREXAMPLE_FOUND",
    ]
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "not a verdict on the agent" in markdown


def test_check_refuses_to_run_code_without_the_flag_or_over_an_existing_output(
    checked, tmp_path: Path
) -> None:
    _, out, task, programs = checked
    refused = runner.invoke(
        app,
        ["data", "check", str(task), "--programs", str(programs), "--output", str(tmp_path / "x")],
    )
    assert refused.exit_code == 2 and "--trust-code" in refused.output
    again = runner.invoke(
        app,
        [
            "data",
            "check",
            str(task),
            "--programs",
            str(programs),
            "--output",
            str(out),
            "--trust-code",
        ],
    )
    assert again.exit_code == 2 and "already exists" in again.output


def test_replay_reproduces_the_finding_and_export_writes_the_eval_case(
    checked, tmp_path: Path
) -> None:
    _, out, _, _ = checked
    replayed = runner.invoke(app, ["data", "replay", str(out / "report.json"), "--trust-code"])
    assert replayed.exit_code == 0 and "Reproduced" in replayed.output
    no_flag = runner.invoke(app, ["data", "replay", str(out / "report.json")])
    assert no_flag.exit_code == 2
    none = runner.invoke(
        app, ["data", "replay", str(out / "report.json"), "--trust-code", "--finding", "9"]
    )
    assert none.exit_code == 2
    exported = runner.invoke(
        app, ["data", "export", str(out / "report.json"), "--output", str(tmp_path / "cases")]
    )
    assert exported.exit_code == 0 and "Exported 1 eval case" in exported.output
    line = json.loads(
        (tmp_path / "cases" / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert line["pack"] == "data" and line["payload"]["dataset"] == ["orders.csv"]


def test_a_task_the_mapper_cannot_hold_is_reported_unsupported(tmp_path: Path) -> None:
    task = make_task(tmp_path / "bad")
    (task / "data" / "orders.csv").write_bytes(b"\xff\xfe\x00 not utf-8")
    programs = tmp_path / "p.jsonl"
    write_programs(programs, [program(CORRECT, "correct")])
    result = runner.invoke(
        app,
        [
            "data",
            "check",
            str(task),
            "--programs",
            str(programs),
            "--output",
            str(tmp_path / "o"),
            "--trust-code",
            "--attempts",
            "5",
        ],
    )
    assert result.exit_code == 0
    report = json.loads((tmp_path / "o" / "report.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["divergence_status"] == "UNSUPPORTED"
    assert report["cases"][0]["errors"][0]["code"] == "UNSUPPORTED_DATA"


def test_audit_runs_an_agent_through_a_subprocess_and_writes_a_live_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(tmp_path / "orders")
    root = Path(__file__).parents[1]
    monkeypatch.setenv("PYTHONPATH", str(root))
    out = tmp_path / "live"
    result = runner.invoke(
        app,
        [
            "data",
            "audit",
            str(task),
            "--agent",
            "tests.data_agents:csv_agent",
            "--output",
            str(out),
            "--trust-code",
            "--pass-env",
            "PYTHONPATH",
            "--baseline-runs",
            "1",
            "--max-trials",
            "1",
            "--max-worlds",
            "2",
            "--attempts",
            "12",
            "--max-runs",
            "6",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    case = report["cases"][0]
    assert (
        case["subject_kind"] == "AGENT" and case["inputs"]["agent"] == "tests.data_agents:csv_agent"
    )
    assert any(w["run_status"] == "NOT_RUN" for w in case["worlds"]) or case["worlds"]
    refused = runner.invoke(
        app,
        [
            "data",
            "audit",
            str(task),
            "--agent",
            "tests.data_agents:csv_agent",
            "--output",
            str(tmp_path / "nope"),
        ],
    )
    assert refused.exit_code == 2 and "--trust-code" in refused.output
