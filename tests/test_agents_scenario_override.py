"""`agents replay --scenario REF`: a report and its scenario can both move.

The report stores the scenario reference as the user typed it, not as an absolute path made at run
time. A replay (and the replay of an exported case) takes ``--scenario REF`` to say where the
scenario is now; when the recorded reference cannot be loaded the command exits 2 and names
``--scenario``.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.evidence import EvalCase
from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.replay import rerun_eval_case

runner = CliRunner()
EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"
TYPED = "booking.py:SCENARIO"  # relative: typed from inside the scenario's directory


@pytest.fixture
def audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """An audit of a copy of the booking scenario, run from the scenario's own directory with a
    relative reference. Returns (the output directory, the scenario directory)."""
    scenario_dir = tmp_path / "original scenario dir"
    scenario_dir.mkdir()
    shutil.copy(EXAMPLES / "booking_scenario.py", scenario_dir / "booking.py")
    out = tmp_path / "original output" / "out"
    monkeypatch.chdir(scenario_dir)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", "careless")
        run_scenario(
            scenario_ref=TYPED,
            agent_command=f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"',
            output_dir=out,
            worlds="fixed",
            k=1,
            only=["booked_24h_01m", "flight_cancelled"],
            trust_code=True,
            timeout_seconds=120,
        )
    return out, scenario_dir


def _moved(
    audited: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Copy the output and the scenario to new places, delete the originals, and move to a third
    directory. Returns (the moved report, the moved scenario file, the third directory)."""
    out, scenario_dir = audited
    new_out = tmp_path / "relocated" / "out"
    new_out.parent.mkdir()
    shutil.copytree(out, new_out)
    new_scenario_dir = tmp_path / "scenario now lives here"
    new_scenario_dir.mkdir()
    shutil.copy(scenario_dir / "booking.py", new_scenario_dir / "booking.py")
    third = tmp_path / "third"
    third.mkdir()
    monkeypatch.chdir(third)  # leave the scenario directory before it is deleted
    shutil.rmtree(out.parent)
    shutil.rmtree(scenario_dir)
    return new_out / "report.json", new_scenario_dir / "booking.py", third


def test_the_report_keeps_the_scenario_reference_as_it_was_typed(
    audited: tuple[Path, Path],
) -> None:
    out, _ = audited
    stored = json.loads((out / "report.json").read_text("utf-8"))["cases"][0]["extensions"]["mcp"]
    assert stored["scenario_ref"] == TYPED


def test_replay_with_scenario_works_when_the_report_and_the_scenario_have_both_moved(
    audited: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, scenario_file, _ = _moved(audited, tmp_path, monkeypatch)
    done = runner.invoke(
        app,
        [
            *["agents", "replay", "--report", str(report), "--trust-code"],
            *["--scenario", f"{scenario_file}:SCENARIO"],
        ],
    )
    assert done.exit_code == 0, done.output
    assert "reproduced" in done.output and "NOT reproduced" not in done.output
    assert done.output.count("reproduced") >= 3  # the baseline and the two worlds


def test_replay_without_scenario_exits_2_and_names_the_flag_when_the_file_is_gone(
    audited: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _, _ = _moved(audited, tmp_path, monkeypatch)
    done = runner.invoke(app, ["agents", "replay", "--report", str(report), "--trust-code"])
    assert done.exit_code == 2, done.output
    assert "--scenario" in done.output and TYPED in done.output
    assert "Traceback" not in done.output


def test_a_scenario_flag_that_cannot_be_loaded_exits_2_with_a_message(
    audited: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _, third = _moved(audited, tmp_path, monkeypatch)
    done = runner.invoke(
        app,
        [
            *["agents", "replay", "--report", str(report), "--trust-code"],
            *["--scenario", str(third / "nowhere.py:SCENARIO")],
        ],
    )
    assert done.exit_code == 2, done.output
    assert "--scenario" in done.output and "Traceback" not in done.output


def test_an_exported_case_replays_from_a_moved_scenario_given_a_reference(
    audited: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, scenario_file, third = _moved(audited, tmp_path, monkeypatch)
    cases_file = third / "cases.jsonl"
    exported = runner.invoke(app, ["agents", "export", str(report), "--output", str(cases_file)])
    assert exported.exit_code == 0, exported.output
    cases = [
        EvalCase.model_validate(json.loads(line))
        for line in cases_file.read_text().split("\n")
        if line
    ]
    assert cases and all(c.payload["scenario_ref"] == TYPED for c in cases)
    for case in cases:
        outcome = rerun_eval_case(case, f"{scenario_file}:SCENARIO")
        assert outcome["reproduced"] is True, outcome
        missing = rerun_eval_case(case)  # the recorded reference no longer exists
        assert missing["reproduced"] is False
        assert "scenario" in missing["detail"] and TYPED in missing["detail"]
