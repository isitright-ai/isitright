"""End-to-end tests: real agent subprocesses talking MCP to real per-world server processes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.evidence import AuditReport, DivergenceStatus
from isitright.packs.mcp.audit import export_eval_cases, run_scenario
from isitright.packs.mcp.model import load_scenario
from isitright.packs.mcp.replay import replay_report, rerun_eval_case
from isitright.packs.mcp.runner import AgentsInputError

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"
SCENARIO_REF = f"{EXAMPLES / 'booking_scenario.py'}:SCENARIO"
DEMO = f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"'
SCHEMA = Path(__file__).parents[1] / "schemas" / "report-0.5.schema.json"
TRAP = ["booked_24h_01m"]
CONTROL = ["flight_cancelled"]
BOTH = [*TRAP, *CONTROL]


def _run(
    tmp_path_factory: pytest.TempPathFactory,
    agent_mode: str,
    only: list[str] | None = None,
    **kwargs: object,
) -> tuple[AuditReport, Path]:
    output = tmp_path_factory.mktemp("agents") / "out"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", agent_mode)
        report = run_scenario(
            scenario_ref=SCENARIO_REF,
            agent_command=DEMO,
            output_dir=output,
            worlds="fixed",
            k=1,
            only=only,
            trust_code=True,
            timeout_seconds=120,
            **kwargs,  # type: ignore[arg-type]
        )
    return report, output


@pytest.fixture(scope="module")
def careless(tmp_path_factory: pytest.TempPathFactory) -> tuple[AuditReport, Path]:
    return _run(tmp_path_factory, "careless")


@pytest.fixture(scope="module")
def refuse(tmp_path_factory: pytest.TempPathFactory) -> tuple[AuditReport, Path]:
    return _run(tmp_path_factory, "refuse", BOTH)


@pytest.fixture(scope="module")
def careful(tmp_path_factory: pytest.TempPathFactory) -> tuple[AuditReport, Path]:
    return _run(tmp_path_factory, "careful", BOTH)


def test_a_careless_agent_violates_the_invariant_in_the_trap_world(
    careless: tuple[AuditReport, Path],
) -> None:
    report, output = careless
    case = report.cases[0]
    assert case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert "DOMAIN_VALIDATED" in case.validity.tiers
    assert case.execution_fidelity.found_on == "SIMULATED"
    violated = {w.id: w.counts["violated"] for w in case.worlds}
    assert violated["booked_24h_01m"] == 1 and violated["original"] == 1
    assert violated["booked_23h_59m"] == 0
    assert case.controls is not None and case.controls.status == "DISCRIMINATING"
    assert case.headline.startswith("Invariant 'no_cancel_without_basis' violated")
    runs = case.extensions["mcp"]["runs"]
    trap_run = next(r for r in runs if r["world_id"] == "booked_24h_01m")
    assert (trap_run["run_status"], trap_run["exit_code"], trap_run["write_calls"]) == (
        "COMPLETED",
        0,
        1,
    )
    run_dir = output / trap_run["run_dir"]
    for name in ("mcp.json", "task.txt", "state_before.json", "state_after.json", "trace.jsonl"):
        assert (run_dir / name).is_file(), name
    config = json.loads((run_dir / "mcp.json").read_text(encoding="utf-8"))
    args = config["mcpServers"]["isitright"]["args"]
    assert args[:2] == ["-m", "isitright.packs.mcp.serve"] and "--trust-code" in args
    after = json.loads((run_dir / "state_after.json").read_text(encoding="utf-8"))
    assert after["bookings"]["B100"]["status"] == "cancelled"


def test_the_written_report_matches_the_checked_in_schema(
    careless: tuple[AuditReport, Path],
) -> None:
    _, output = careless
    data = json.loads((output / "report.json").read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(data)
    assert AuditReport.model_validate(data).cases[0].case_id == "booking-cancellation"
    assert (output / "report.md").is_file()


def test_recorded_runs_replay_offline(careless: tuple[AuditReport, Path]) -> None:
    report, output = careless
    outcomes = replay_report(report, load_scenario(SCENARIO_REF), output)
    assert len(outcomes) == 5 and all(o.reproduced for o in outcomes), outcomes


def test_every_finding_exports_as_an_eval_case_that_reproduces_its_disagreement(
    careless: tuple[AuditReport, Path],
) -> None:
    report, output = careless
    cases = export_eval_cases(SCENARIO_REF, report, output)
    assert len(cases) == len(report.cases[0].findings) >= 2
    for case in cases:
        assert rerun_eval_case(case)["reproduced"] is True, case.case_id


def test_cli_replay_reproduces_a_report(careless: tuple[AuditReport, Path]) -> None:
    _, output = careless
    runner = CliRunner()
    refused = runner.invoke(app, ["agents", "replay", "--report", str(output / "report.json")])
    assert refused.exit_code == 2 and "--trust-code" in refused.output
    result = runner.invoke(
        app, ["agents", "replay", "--report", str(output / "report.json"), "--trust-code"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("reproduced") == 5 and "NOT reproduced" not in result.output
    tampered = output / "runs" / "booked_24h_01m" / "1" / "state_after.json"
    saved = tampered.read_text(encoding="utf-8")
    tampered.write_text(saved.replace("cancelled", "active"), encoding="utf-8")
    try:
        bad = runner.invoke(
            app, ["agents", "replay", "--report", str(output / "report.json"), "--trust-code"]
        )
    finally:
        tampered.write_text(saved, encoding="utf-8")
    assert bad.exit_code == 1 and "NOT reproduced" in bad.output


def test_an_agent_that_refuses_everything_is_caught_by_the_control_world(
    refuse: tuple[AuditReport, Path],
) -> None:
    report, _ = refuse
    case = report.cases[0]
    assert not any(w.counts["violated"] for w in case.worlds)
    assert case.controls is not None and case.controls.status == "NOT_DISCRIMINATING"
    assert case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert {o.kind for f in case.findings for o in f.oracles if o.outcome == "NOT_MET"} == {
        "REFERENCE_PROGRAM"
    }
    assert [f.world_id for f in case.findings] == ["flight_cancelled"]
    assert case.headline.startswith("Expected behavior not reached")


def test_a_careful_agent_has_no_findings_and_working_controls(
    careful: tuple[AuditReport, Path],
) -> None:
    report, _ = careful
    case = report.cases[0]
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert case.controls is not None and case.controls.status == "DISCRIMINATING"
    assert case.findings == []
    assert case.headline.endswith("control worlds behaved as expected")
    assert all(r["tool_calls"] >= 2 for r in case.extensions["mcp"]["runs"])


def test_cli_exit_codes_follow_the_fail_on_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    def invoke(only: list[str], agent_mode: str, name: str, *extra: str):  # type: ignore[no-untyped-def]
        monkeypatch.setenv("DEMO_AGENT_MODE", agent_mode)
        return runner.invoke(
            app,
            [
                "agents",
                "run",
                "--trust-code",
                "--scenario",
                SCENARIO_REF,
                "--agent-command",
                DEMO,
                "--worlds",
                "fixed",
                "--trials",
                "1",
                "--timeout",
                "120",
                *[x for w in only for x in ("--world", w)],
                "--output-dir",
                str(tmp_path / name),
                *extra,
            ],
        )

    default = invoke(TRAP, "careless", "default")
    assert default.exit_code == 0, default.output
    assert "violated" in default.output and "COUNTEREXAMPLE_FOUND" in default.output
    policy = invoke(TRAP, "careless", "policy", "--fail-on", "invariant-violation")
    assert policy.exit_code == 3
    # A control-world mismatch is a finding, but not an invariant violation.
    soft = invoke(CONTROL, "refuse", "soft", "--fail-on", "invariant-violation")
    assert soft.exit_code == 0, soft.output
    hard = invoke(CONTROL, "refuse", "hard", "--fail-on", "any-finding")
    assert hard.exit_code == 3


def test_cli_rejects_missing_consent_and_bad_scenarios(tmp_path: Path) -> None:
    runner = CliRunner()
    base = ["agents", "run", "--agent-command", DEMO]
    no_consent = runner.invoke(
        app, [*base, "--scenario", SCENARIO_REF, "--output-dir", str(tmp_path / "a")]
    )
    assert no_consent.exit_code == 2 and "trust_code" in no_consent.output
    bad = runner.invoke(
        app,
        [
            *base,
            "--trust-code",
            "--scenario",
            "nonexistent_mod:S",
            "--output-dir",
            str(tmp_path / "b"),
        ],
    )
    assert bad.exit_code == 2 and "cannot load scenario" in bad.output


# --- failure modes that need no MCP traffic, so they are cheap ---------------------------------


def _quick(
    tmp_path: Path, command: str, only: list[str] | None = None, **kwargs: object
) -> AuditReport:
    return run_scenario(
        scenario_ref=SCENARIO_REF,
        agent_command=command,
        output_dir=tmp_path / "out",
        worlds="fixed",
        k=int(kwargs.pop("k", 1)),  # type: ignore[call-overload]
        only=only if only is not None else TRAP,
        trust_code=True,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_hung_agent_is_killed_and_reported_inconclusive(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(120)"'
    case = _quick(tmp_path, command, timeout_seconds=2).cases[0]
    runs = case.extensions["mcp"]["runs"]
    assert [r["run_status"] for r in runs] == ["TIMEOUT", "TIMEOUT"]  # baseline and the world
    assert runs[0]["exit_code"] is None and runs[0]["outcome"] is None
    assert case.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert case.headline.startswith("Inconclusive")


def test_a_crashing_agent_is_reported_as_a_subject_error(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "import sys; sys.exit(3)"'
    case = _quick(tmp_path, command).cases[0]
    run = case.extensions["mcp"]["runs"][0]
    assert (run["run_status"], run["exit_code"]) == ("SUBJECT_ERROR", 3)
    assert case.divergence_status is DivergenceStatus.INCONCLUSIVE


def test_an_agent_that_never_connects_is_evaluated_on_the_untouched_world(tmp_path: Path) -> None:
    case = _quick(tmp_path, f'"{sys.executable}" -c "pass"', k=2).cases[0]
    runs = case.extensions["mcp"]["runs"]
    assert [r["tool_calls"] for r in runs] == [0, 0, 0, 0]
    assert all(r["outcome"] == "MET" for r in runs)  # not cancelling is right here
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert case.stability is not None and case.stability.k == 2


def test_placeholders_and_environment_reach_the_agent(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "env = {k: v for k, v in os.environ.items() if k.startswith('ISITRIGHT_')}\n"
        "out = {'argv': sys.argv[1:], 'env': env}\n"
        "json.dump(out, open(os.path.join(sys.argv[1], 'probe.json'), 'w'))\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{probe}" "{{run_dir}}" "{{mcp_config}}" "{{task_file}}"'
    case = _quick(tmp_path, command).cases[0]
    run = next(r for r in case.extensions["mcp"]["runs"] if r["world_id"] == "booked_24h_01m")
    run_dir = tmp_path / "out" / run["run_dir"]
    seen = json.loads((run_dir / "probe.json").read_text(encoding="utf-8"))
    assert seen["argv"] == [str(run_dir), str(run_dir / "mcp.json"), str(run_dir / "task.txt")]
    assert seen["env"]["ISITRIGHT_WORLD"] == "booked_24h_01m"
    assert seen["env"]["ISITRIGHT_MCP_CONFIG"] == str(run_dir / "mcp.json")
    assert "cust_1" in (run_dir / "task.txt").read_text(encoding="utf-8")


def test_invalid_worlds_are_not_run(tmp_path: Path) -> None:
    path = tmp_path / "invalid.py"
    path.write_text(
        "import dataclasses, sys\n"
        f"sys.path.insert(0, {str(EXAMPLES)!r})\n"
        "from booking_scenario import SCENARIO as _S\n"
        "bad = dataclasses.replace(_S.fixed_worlds[0], validate=lambda s: ['impossible state'])\n"
        "SCENARIO = dataclasses.replace(_S, fixed_worlds=[bad])\n",
        encoding="utf-8",
    )
    report = run_scenario(
        scenario_ref=f"{path}:SCENARIO",
        agent_command=f'"{sys.executable}" -c "pass"',
        output_dir=tmp_path / "out",
        worlds="fixed",
        trust_code=True,
    )
    case = report.cases[0]
    assert case.divergence_status is DivergenceStatus.UNSUPPORTED
    bad = next(w for w in case.worlds if w.id == "original")
    assert bad.validity.status == "INVALID" and bad.validity.problems == ["impossible state"]
    assert all(r["world_id"] != "original" for r in case.extensions["mcp"]["runs"])


def test_run_scenario_input_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = f'"{sys.executable}" -c "pass"'
    with pytest.raises(AgentsInputError, match="trust_code"):
        run_scenario(scenario_ref=SCENARIO_REF, agent_command=command, output_dir=tmp_path / "x")
    with pytest.raises(AgentsInputError, match="at least 1"):
        _quick(tmp_path, command, k=0)
    (tmp_path / "out").mkdir()
    with pytest.raises(AgentsInputError, match="already exists"):
        _quick(tmp_path, command)
    with pytest.raises(AgentsInputError, match="empty"):
        run_scenario(
            scenario_ref=SCENARIO_REF,
            agent_command="  ",
            output_dir=tmp_path / "y",
            trust_code=True,
        )
    with pytest.raises(AgentsInputError, match="cannot start"):
        run_scenario(
            scenario_ref=SCENARIO_REF,
            agent_command="definitely-not-a-real-executable-xyz",
            output_dir=tmp_path / "z",
            worlds="fixed",
            only=TRAP,
            trust_code=True,
        )
    import importlib.util

    original = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "mcp" else original(name, *a)
    )
    with pytest.raises(AgentsInputError, match="isitright\\[mcp\\]"):
        run_scenario(
            scenario_ref=SCENARIO_REF,
            agent_command=command,
            output_dir=tmp_path / "w",
            trust_code=True,
        )


def test_the_server_refuses_to_run_without_consent(tmp_path: Path) -> None:
    import subprocess

    world = tmp_path / "world.json"
    world.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "isitright.packs.mcp.serve",
            "--scenario",
            SCENARIO_REF,
            "--fixed",
            "booked_24h_01m",
            "--run-dir",
            str(tmp_path / "r"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "--trust-code" in result.stderr
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "isitright.packs.mcp.serve",
            "--scenario",
            SCENARIO_REF,
            "--fixed",
            "missing",
            "--run-dir",
            str(tmp_path / "r2"),
            "--trust-code",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 2 and "no world" in bad.stderr


def test_the_stack_under_test_and_its_cost_are_read_from_the_transcript(tmp_path: Path) -> None:
    agent = tmp_path / "writes_transcript.py"
    agent.write_text(
        "import json, os\n"
        "data = {'provider': 'prov', 'model': 'mod-1', 'sdk_versions': {'mcp': '2.3.0'},\n"
        "        'settings': {'max_turns': 3}, 'stop_reason': 'final',\n"
        "        'usage': [{'input_tokens': 7, 'output_tokens': 2, 'cost': 0.5}]}\n"
        "path = os.path.join(os.environ['ISITRIGHT_RUN_DIR'], 'transcript.json')\n"
        "json.dump(data, open(path, 'w'))\n",
        encoding="utf-8",
    )
    case = _quick(tmp_path, f'"{sys.executable}" "{agent}"', k=2).cases[0]
    subject = case.extensions["mcp"]["subject"]
    assert (subject["provider"], subject["model"]) == ("prov", "mod-1")
    assert subject["harness_name"] == "writes_transcript"
    assert subject["harness_version"].startswith("sha256:")
    runs = case.extensions["mcp"]["runs"]
    assert [(r["model_calls"], r["input_tokens"], r["output_tokens"]) for r in runs] == [
        (1, 7, 2)
    ] * 4
    assert all(r["agent_stop_reason"] == "final" and r["cost"] == 0.5 for r in runs)
    text = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "Stack under test: prov mod-1; harness writes_transcript sha256:" in text
    data = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(data)


def test_an_agent_without_a_transcript_has_no_subject(tmp_path: Path) -> None:
    case = _quick(tmp_path, f'"{sys.executable}" -c "pass"').cases[0]
    assert case.extensions["mcp"]["subject"] is None
    assert case.extensions["mcp"]["runs"][0].get("subject") is None


def test_progress_reports_each_run_with_a_marker(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(120)"'
    events: list[tuple[str, str]] = []
    _quick(tmp_path, command, timeout_seconds=2, progress=lambda w, m: events.append((w, m)))
    assert [m for _, m in events] == ["E", "E"]  # neither the baseline nor the world completed
    assert events[0][0] != events[1][0]


def test_cli_prints_progress_on_stderr_and_a_summary_with_elapsed_time(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(120)"'
    result = CliRunner().invoke(
        app,
        [
            "agents",
            "run",
            "--trust-code",
            "--scenario",
            SCENARIO_REF,
            "--agent-command",
            command,
            "--worlds",
            "fixed",
            "--world",
            TRAP[0],
            "--trials",
            "1",
            "--timeout",
            "2",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert "Agent runs: " in result.output and ": E" in result.output
    assert "Runs: 2. Elapsed: " in result.output
