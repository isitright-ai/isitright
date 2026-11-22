# Proposed fixture: pending owner review
# The expected values here (what a live data finding must carry, what its replay verifies, what
# its export holds) were written by the author of the implementation.
"""N2 follow-up: a live data finding can be inspected and verified, and exported.

Each test goes through the real CLI (`data audit`, `data replay`, `data export`) with an agent run
in a subprocess. Two agents make the same mistake (a blank amount counts as zero): one returns the
code it ran, one returns only an answer. With `--max-trials 3` the paired test cannot decide, so the
failures are observations; with the default pair limit it decides a rate increase.

The replay verifies recorded evidence. It never runs the agent, and says so.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from isitright.cli import app

pytest.importorskip("pandas")
from .data_factories import make_task

runner = CliRunner()
ROOT = Path(__file__).parents[1]
_RUNS: dict[tuple[str, str], tuple[Path, Any]] = {}


@pytest.fixture(scope="module")
def audited(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Run `data audit` once per (agent, max-trials) and share the output directory."""

    def run(agent: str, max_trials: int, *extra: str) -> tuple[Path, Any]:
        key = (agent, f"{max_trials}{extra}")
        if key not in _RUNS:
            base = tmp_path_factory.mktemp(f"live-{agent}-{max_trials}")
            out = base / "out"
            saved = os.environ.get("PYTHONPATH")
            os.environ["PYTHONPATH"] = str(ROOT)
            try:
                result = runner.invoke(
                    app,
                    [
                        "data", "audit", str(make_task(base / "orders")),
                        "--agent", f"tests.data_agents:{agent}", "--output", str(out),
                        "--trust-code", "--pass-env", "PYTHONPATH", "--baseline-runs", "2",
                        "--max-trials", str(max_trials), "--max-worlds", "2",
                        "--attempts", "40", *extra,
                    ],
                )  # fmt: skip
            finally:
                if saved is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = saved
            _RUNS[key] = (out, result)
        return _RUNS[key]

    return run


def _report(out: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return data


def _replay(out: Path, number: int) -> Any:
    return runner.invoke(
        app, ["data", "replay", str(out / "report.json"), "--finding", str(number), "--trust-code"]
    )


def _run_program(code: str, directory: Path) -> str:
    buffer, here = io.StringIO(), os.getcwd()
    os.chdir(directory)
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, {})
    finally:
        os.chdir(here)
    return buffer.getvalue().strip()


def _gold_result(directory: Path) -> Any:
    scope: dict[str, Any] = {}
    here = os.getcwd()
    os.chdir(directory)
    try:
        exec((directory / "gold.py").read_text(encoding="utf-8"), scope)
    finally:
        os.chdir(here)
    return scope["result"]


@pytest.mark.parametrize("agent", ["forgot_dropna", "answer_only"])
def test_every_live_finding_names_a_replay_artifact_that_exists_and_replays(
    audited: Any, agent: str
) -> None:
    out, result = audited(agent, 3)
    assert result.exit_code == 0, result.output
    case = _report(out)["cases"][0]
    assert case["divergence_status"] == "OBSERVED_FAILURE"
    findings = case["findings"]
    assert findings
    for number, finding in enumerate(findings, start=1):
        artifact = out / finding["replay"]["artifact"]
        assert artifact.is_file(), finding["replay"]
        assert finding["replay"]["command"].endswith(f"--finding {number} --trust-code")
        data = json.loads(artifact.read_text(encoding="utf-8"))
        assert data["host"]["mode"] == "live" and data["inputs"]["agent_rerun"] is False
        assert data["inputs"]["gold_code"] and data["inputs"]["question"]
        assert data["expected"]["recorded_outcomes"] and set(
            data["expected"]["recorded_outcomes"]
        ) == {"NOT_MET"}
        replayed = _replay(out, number)
        assert replayed.exit_code == 0, replayed.output
        assert "Reproduced the recorded observation." in replayed.output
        assert "The agent was not rerun" in replayed.output
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "It replays the recorded observation; the agent is not rerun." in markdown


@pytest.mark.parametrize("agent", ["forgot_dropna", "answer_only"])
def test_every_live_finding_is_built_from_the_world_its_replay_artifact_holds(
    audited: Any, agent: str
) -> None:
    """N5: the finding's world, and every part tied to it, is the world the artifact stores."""
    from isitright.core.shown import world_json_fingerprint

    out, _ = audited(agent, 3)
    findings = _report(out)["cases"][0]["findings"]
    assert findings
    for finding in findings:
        stored = json.loads((out / finding["replay"]["artifact"]).read_text(encoding="utf-8"))
        assert finding["world_fingerprint"] == world_json_fingerprint(stored["world"])
        assert set(finding["built_from"]) >= {"validity", "world_diff", "counts", "replay"}
        assert set(finding["built_from"].values()) == {finding["world_fingerprint"]}


def test_the_replay_verifies_the_evidence_it_claims_and_catches_a_change(audited: Any) -> None:
    out, _ = audited("forgot_dropna", 3)
    case = _report(out)["cases"][0]
    artifact = out / case["findings"][0]["replay"]["artifact"]
    original = artifact.read_text(encoding="utf-8")
    data = json.loads(original)
    try:
        # A recorded comparison that the reference does not give.
        data["expected"]["recorded_outcomes"][0] = "MET"
        artifact.write_text(json.dumps(data), encoding="utf-8")
        failed = _replay(out, 1)
        assert failed.exit_code == 1 and "recorded_outcomes" in failed.output
        # A reference answer that the recorded world does not give.
        data = json.loads(original)
        data["expected"]["gold_answer"] = {"north_mean": -1.0}
        artifact.write_text(json.dumps(data), encoding="utf-8")
        failed = _replay(out, 1)
        assert failed.exit_code == 1 and "gold_answer" in failed.output
        # An answer that the recorded code does not give.
        data = json.loads(original)
        data["expected"]["code_answers"][0] = "@north_mean[0.00]"
        artifact.write_text(json.dumps(data), encoding="utf-8")
        failed = _replay(out, 1)
        assert failed.exit_code == 1 and "code_answers" in failed.output
    finally:
        artifact.write_text(original, encoding="utf-8")
    assert _replay(out, 1).exit_code == 0


def test_a_code_producing_agent_has_its_code_recorded_and_executed_on_replay(
    audited: Any,
) -> None:
    out, _ = audited("forgot_dropna", 3)
    finding = _report(out)["cases"][0]["findings"][0]
    artifact = json.loads((out / finding["replay"]["artifact"]).read_text(encoding="utf-8"))
    runs = artifact["inputs"]["runs"]
    assert runs and all(r["code"] and "fillna(0)" in r["code"] for r in runs)
    assert artifact["expected"]["code_answers"] == [r["answer"] for r in runs]


def test_an_answer_only_agent_gets_no_invented_code(audited: Any) -> None:
    out, _ = audited("answer_only", 3)
    finding = _report(out)["cases"][0]["findings"][0]
    artifact = json.loads((out / finding["replay"]["artifact"]).read_text(encoding="utf-8"))
    runs = artifact["inputs"]["runs"]
    assert runs and all(r["code"] is None and r["answer"] for r in runs)
    assert artifact["expected"]["code_answers"] == [None] * len(runs)
    # The recorded reference code is the task's, and is not presented as the agent's.
    assert artifact["inputs"]["gold_code"].strip().startswith("import pandas")


@pytest.mark.parametrize("agent", ["forgot_dropna", "answer_only"])
def test_export_holds_the_dataset_reference_expectation_and_observation(
    audited: Any, tmp_path: Path, agent: str
) -> None:
    out, _ = audited(agent, 3)
    report = out / "report.json"
    default = runner.invoke(app, ["data", "export", str(report), "--output", str(tmp_path / "a")])
    assert default.exit_code == 0, default.output
    assert "Exported 0 eval case(s)" in default.output
    assert "graded OBSERVED_FAILURE were not exported" in default.output
    asked = runner.invoke(
        app, ["data", "export", str(report), "--output", str(tmp_path / "b"), "--include-observed"]
    )
    assert asked.exit_code == 0, asked.output
    index = [
        json.loads(line)
        for line in (tmp_path / "b" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    findings = _report(out)["cases"][0]["findings"]
    assert len(index) == len(findings) >= 1
    for case in index:
        directory = tmp_path / "b" / case["case_id"]
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        dataset = (directory / "orders.csv").read_text(encoding="utf-8")
        assert dataset.startswith("id,region,amount,note") and len(dataset.splitlines()) > 1
        assert (
            (directory / "question.txt").read_text(encoding="utf-8").startswith("What is the mean")
        )
        assert (
            (directory / "gold.py").read_text(encoding="utf-8").strip().startswith("import pandas")
        )
        # internally consistent: the reference on the exported dataset gives the expected answer
        assert _gold_result(directory) == expected["expected_answer"]
        assert expected["evidence_grade"] == "OBSERVED_FAILURE"
        assert "not rerun" in expected["scope"]
        runs = expected["recorded_observation"]["runs"]
        assert runs and {r["outcome"] for r in runs} == {"NOT_MET"}
        for run in runs:
            assert run["answer"] and run["answer"] != expected["expected_answer"]
            if agent == "forgot_dropna":
                # the recorded code, run on the exported dataset, gives the recorded answer
                assert _run_program(run["code"], directory) == run["answer"]
            else:
                assert run["code"] is None
        assert case["payload"]["gold_program"] == "gold.py"
        assert case["expectation"]["recorded_observation"]["runs"] == runs


def test_a_decided_rate_increase_is_exported_by_default(audited: Any, tmp_path: Path) -> None:
    out, result = audited("forgot_dropna", 20)
    assert result.exit_code == 0, result.output
    case = _report(out)["cases"][0]
    assert case["divergence_status"] == "COUNTEREXAMPLE_FOUND"
    rate = [f for f in case["findings"] if f["evidence_grade"] == "RATE_INCREASE"]
    assert rate
    exported = runner.invoke(
        app, ["data", "export", str(out / "report.json"), "--output", str(tmp_path / "c")]
    )
    assert exported.exit_code == 0, exported.output
    assert f"Exported {len(rate)} eval case(s)" in exported.output
    number = case["findings"].index(rate[0]) + 1
    assert _replay(out, number).exit_code == 0


def test_the_gate_is_off_unless_chosen(audited: Any) -> None:
    """Omitting --fail-on never fails the build; the policies are opt-in."""
    for agent, trials in (("forgot_dropna", 3), ("forgot_dropna", 20)):
        _, result = audited(agent, trials)
        assert result.exit_code == 0, result.output  # no --fail-on given
    gated = {  # (agent, max-trials, --fail-on) -> exit code
        ("forgot_dropna", 3, "rate-increase"): 0,
        ("forgot_dropna", 3, "observed-failure"): 3,
        ("forgot_dropna", 20, "rate-increase"): 3,
        ("forgot_dropna", 20, "observed-failure"): 3,
        ("forgot_dropna", 3, "none"): 0,
    }
    for (agent, trials, policy), code in gated.items():
        _, result = audited(agent, trials, "--fail-on", policy)
        assert result.exit_code == code, (agent, trials, policy, result.output)
