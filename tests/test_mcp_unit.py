"""MCP pack unit tests: scenario definition, oracle, report assembly and offline replay.

They carry the earlier agent-pack assertions (validation, evaluation per world, controls, headlines,
the report contract, replay, interference, transcripts) to the declared-scenario design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.evidence import AuditReport, CaseReport, DivergenceStatus
from isitright.core.mutations import SetField, Timer, Trigger, World
from isitright.core.oracles import Outcome, Role
from isitright.core.spec import ParamSpec, ToolSpec, WorldSpec
from isitright.core.stochastic import Budget, RunOutcome
from isitright.core.world import State
from isitright.packs.mcp.audit import (
    RunWorld,
    WorldResult,
    build_report,
    prepare_worlds,
    write_report,
)
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    FixedWorld,
    Interference,
    Invariant,
    Layout,
    McpScenario,
    ScenarioError,
    ScenarioOracle,
    ToolDef,
    absolute_reference,
    load_scenario,
    render,
    split_reference,
)
from isitright.packs.mcp.oracle import EvaluationError, judge_run, reference_outcome
from isitright.packs.mcp.replay import replay_run
from isitright.packs.mcp.runner import harness_identity, read_trace, read_transcript
from isitright.packs.mcp.serve import world_of, write_state

EXAMPLE = Path(__file__).parents[1] / "examples" / "agents" / "booking_scenario.py"
SCHEMA = Path(__file__).parents[1] / "schemas" / "report-0.5.schema.json"


@pytest.fixture(scope="module")
def booking() -> McpScenario:
    return load_scenario(f"{EXAMPLE}:SCENARIO")


def _event(index: int, name: str, arguments: dict[str, Any], result: str = "{}") -> dict[str, Any]:
    return {
        "index": index,
        "name": name,
        "arguments": arguments,
        "result": result,
        "is_error": False,
    }


# --- a tiny scenario for definition and interference tests ---------------------------------------

_SCHEMA = EntitySchema(
    collections=[CollectionSpec(name="things", key="id", fields=[FieldSpec(name="id")])]
)


def _tiny(
    tools: list[ToolDef] | None = None,
    fixed: list[FixedWorld] | None = None,
    **kwargs: Any,
) -> McpScenario:
    tools = (
        tools if tools is not None else [ToolDef("t", "d", {"type": "object"}, lambda s, a: "ok")]
    )
    spec = WorldSpec(
        id="tiny",
        schema=_SCHEMA,
        params=[ParamSpec(name="n", type="int", default=0)],
        tools=[ToolSpec(name=t.name, writes=t.writes) for t in tools],
    )
    return McpScenario(
        id=kwargs.pop("id", "tiny"),
        task="t",
        spec=spec,
        tools=tools,
        base=State({"things": ({"id": "a"},)}, {"things": "id"}, {"n": 0}),
        layout=Layout(keyed=("things",), scalars=(), block="service"),
        oracle=ScenarioOracle("o", [], lambda call: None),
        fixed_worlds=fixed or (),
        **kwargs,
    )


def _fixed(world_id: str = "w", role: str = "baseline", **kwargs: Any) -> FixedWorld:
    return FixedWorld(
        world_id, role, "d", lambda: {"things": {"a": {"id": "a"}}, "service": {"n": 0}}, **kwargs
    )  # type: ignore[arg-type]


# --- scenario definition and loading ----------------------------------------------------------


def test_scenario_rejects_malformed_definitions() -> None:
    with pytest.raises(ScenarioError, match="at least one tool"):
        _tiny(tools=[])
    tool = ToolDef("t", "d", {}, lambda s, a: 1)
    with pytest.raises(ScenarioError, match="duplicate tool"):
        _tiny(tools=[tool, tool])
    with pytest.raises(ScenarioError, match="duplicate world"):
        _tiny(fixed=[_fixed(), _fixed()])
    with pytest.raises(ScenarioError, match="needs an expectation"):
        _tiny(fixed=[_fixed("c", "control")])
    with pytest.raises(ScenarioError, match="must match"):
        _tiny(id="bad id")
    with pytest.raises(ScenarioError, match="must match"):
        _tiny(fixed=[_fixed("../x")])


def test_scenario_rejects_reserved_tool_names_and_duplicate_interferences() -> None:
    with pytest.raises(ScenarioError, match="reserved"):
        _tiny(tools=[ToolDef(WORLD_CHANGE, "d", {}, lambda s, a: 1)])
    twice = Interference("x", lambda s, n, a: True, lambda s: {})
    with pytest.raises(ScenarioError, match="duplicate interference"):
        _tiny(fixed=[_fixed(interferences=[twice, twice])])


def test_hints_that_do_not_resolve_are_rejected_at_load() -> None:
    from isitright.core.hints import Hint, Hints

    bad = Hints([Hint(kind="gate", args={"collection": "things", "field": "nope", "allows": []})])
    with pytest.raises(ScenarioError, match="no field 'nope'"):
        _tiny(hints=bad)


def test_scenario_world_lookup(booking: McpScenario) -> None:
    assert booking.fixed("booked_23h_59m").role == "control"
    with pytest.raises(ScenarioError, match="no world"):
        booking.fixed("missing")


def test_load_scenario_from_file_module_and_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "my_scenarios.py"
    module.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).parent.parent)!r})\n"
        "from tests.test_mcp_unit import _tiny\n"
        "S = _tiny(id='m')\n"
        "def factory():\n    return S\n"
        "NOT_ONE = 3\n",
        encoding="utf-8",
    )
    assert load_scenario(f"{module}:S").id == "m"
    assert load_scenario(f"{module}:factory").id == "m"
    monkeypatch.syspath_prepend(str(tmp_path))
    assert load_scenario("my_scenarios:S").id == "m"
    with pytest.raises(ScenarioError, match="not a McpScenario"):
        load_scenario(f"{module}:NOT_ONE")
    with pytest.raises(ScenarioError, match="cannot load"):
        load_scenario(f"{module}:missing")
    with pytest.raises(ScenarioError, match="cannot load"):
        load_scenario(f"{tmp_path / 'absent.py'}:S")
    with pytest.raises(ScenarioError, match="cannot load"):
        load_scenario("no_such_module_anywhere:S")


def test_reference_helpers() -> None:
    assert split_reference("a.b:c") == ("a.b", "c")
    assert split_reference(r"C:\x\s.py:SCENARIO") == (r"C:\x\s.py", "SCENARIO")
    for bad in ("nocolon", ":attr", "mod:"):
        with pytest.raises(ScenarioError):
            split_reference(bad)
    assert absolute_reference("pkg.mod:S") == "pkg.mod:S"
    assert Path(absolute_reference("some/file.py:S").rpartition(":")[0]).is_absolute()
    assert render("text") == "text"
    assert render({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


# --- the oracle: invariants, roles, judgements -------------------------------------------------


def _cancel_event(index: int = 0) -> dict[str, Any]:
    return _event(index, "cancel_booking", {"booking_id": "B100"})


def _judge(
    booking: McpScenario, world_id: str, after_status: str, trace: list[dict[str, Any]]
) -> Any:
    world, interferences = world_of(booking, booking.fixed(world_id))
    reference = reference_outcome(booking, world, interferences)
    before = booking.layout.to_service(world.state)
    after = json.loads(json.dumps(before))
    after["bookings"]["B100"]["status"] = after_status
    return reference, judge_run(booking, reference, before, after, trace)


def test_roles_come_from_the_reference_procedure(booking: McpScenario) -> None:
    roles = {
        w.id: reference_outcome(booking, *world_of(booking, w)).role for w in booking.fixed_worlds
    }
    assert roles == {
        "original": Role.TRAP,
        "booked_24h_01m": Role.TRAP,
        "booked_23h_59m": Role.CONTROL,
        "flight_cancelled": Role.CONTROL,
    }


def test_invariant_and_oracle_are_judged_per_world(booking: McpScenario) -> None:
    _, violated = _judge(booking, "booked_24h_01m", "cancelled", [_cancel_event()])
    assert [name for name, _ in violated.violations] == ["no_cancel_without_basis"]
    assert violated.outcome is Outcome.NOT_MET
    _, kept = _judge(booking, "booked_24h_01m", "active", [])
    assert kept.violations == [] and kept.outcome is Outcome.MET
    _, control = _judge(booking, "booked_23h_59m", "cancelled", [_cancel_event()])
    assert control.violations == [] and control.outcome is Outcome.MET


def test_a_raising_check_is_a_scenario_error_not_a_finding() -> None:
    def boom(before: dict, after: dict, trace: list) -> list[str]:
        raise RuntimeError("bug in the invariant")

    scenario = _tiny()
    scenario.oracle = ScenarioOracle("o", [Invariant("i", "d", boom)], lambda call: None)
    reference = reference_outcome(scenario, World(scenario.base))
    with pytest.raises(EvaluationError, match="bug in the invariant"):
        judge_run(scenario, reference, {}, {}, [])


def test_checks_get_copies_so_they_cannot_corrupt_the_record() -> None:
    def mutate(before: dict, after: dict, trace: list) -> list[str]:
        before["n"] = 99
        return []

    scenario = _tiny()
    scenario.oracle = ScenarioOracle("o", [Invariant("i", "d", mutate)], lambda call: None)
    state = {"n": 0}
    reference = reference_outcome(scenario, World(scenario.base))
    judge_run(scenario, reference, state, state, [])
    assert state == {"n": 0}


def test_a_world_outside_the_oracles_assumptions_cannot_be_judged() -> None:
    scenario = _tiny()
    scenario.oracle = ScenarioOracle(
        "o", [], lambda call: None, judgeable=lambda w: "outside the stated assumptions"
    )
    reference = reference_outcome(scenario, World(scenario.base))
    assert reference.role is Role.UNJUDGEABLE
    verdict = judge_run(scenario, reference, {}, {}, [])
    assert verdict.outcome is Outcome.CANNOT_JUDGE
    assert "outside the stated assumptions" in verdict.messages[0]


def test_world_validation_statuses() -> None:
    scenario = _tiny(
        fixed=[
            _fixed("none"),
            _fixed("good", validate=lambda s: []),
            _fixed("bad", validate=lambda s: ["bad"]),
            _fixed("boom", validate=lambda s: 1 / 0),  # type: ignore[arg-type,return-value]
        ]
    )
    worlds, _ = prepare_worlds(scenario, "fixed", attempts=1, seed=0)
    by_id = {w.id: w.validity for w in worlds}
    assert by_id["none"].status == "NOT_ASSESSED"
    assert by_id["good"].status == "VALID" and "DOMAIN_VALIDATED" in by_id["good"].tiers
    assert by_id["bad"].status == "INVALID" and by_id["bad"].problems == ["bad"]
    assert by_id["boom"].status == "INVALID" and "validation raised" in by_id["boom"].problems[0]


def test_read_trace_orders_events_and_tolerates_absence(tmp_path: Path) -> None:
    assert read_trace(tmp_path / "missing.jsonl") == []
    rows = [_event(1, "b", {}), _event(0, "a", {"x": 1})]
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert [e["name"] for e in read_trace(path)] == ["a", "b"]


# --- timing: a world that changes during the run -------------------------------------------------


def _shifty(use_timer: bool = False) -> McpScenario:
    def read(state: dict, args: dict) -> int:
        return int(state["service"]["n"])

    def bump(state: dict, args: dict) -> int:
        state["service"]["n"] += 1
        return int(state["service"]["n"])

    tools = [ToolDef("read", "d", {}, read), ToolDef("bump", "d", {}, bump, writes=True)]
    scenario = _tiny(tools=tools)
    if use_timer:
        return scenario
    interference = Interference(
        "drift",
        lambda s, name, a: name == "read",
        lambda s: s["service"].__setitem__("n", s["service"]["n"] + 100) or {"n": 100},
    )
    scenario.fixed_worlds = [_fixed(interferences=[interference])]
    return scenario


def test_interference_fires_once_on_a_matching_successful_call() -> None:
    from isitright.packs.mcp.runtime import ServiceRuntime

    scenario = _shifty()
    world, interferences = world_of(scenario, scenario.fixed("w"))
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    runtime.call("bump", {})
    assert runtime.after_call("bump", {}) == []
    runtime.call("read", {})
    assert runtime.after_call("read", {}) == [{"n": 100}]
    assert runtime.service["service"]["n"] == 101
    assert runtime.after_call("read", {}) == []


def test_declarative_timers_and_response_edits_act_during_a_run() -> None:
    from isitright.core.mutations import ResponseEdit
    from isitright.packs.mcp.runtime import ServiceRuntime

    scenario = _shifty(use_timer=True)
    timer = Timer(
        name="t1",
        trigger=Trigger(tool="read"),
        edits=[SetField(collection="things", key="a", path=["id"], value="a")],
        record={"changed": True},
    )
    edit = ResponseEdit(tool="bump", op="empty_ack", first_only=True)
    runtime = ServiceRuntime.for_world(scenario, World(scenario.base, (edit,), (timer,)))
    assert runtime.call("bump", {}) == "{}" and runtime.call("bump", {}) == "2"
    assert runtime.after_call("read", {}) == [{"changed": True}]
    assert runtime.after_call("read", {}) == []


def _record_with_change(scenario: McpScenario, run_dir: Path) -> list[dict[str, Any]]:
    """Write the files the serving process writes for read, bump (the change follows read)."""
    from isitright.packs.mcp.runtime import ServiceRuntime

    run_dir.mkdir(parents=True)
    world, interferences = world_of(scenario, scenario.fixed("w"))
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    write_state(run_dir / "state_before.json", runtime.service)
    rows: list[dict[str, Any]] = []
    for name in ("read", "bump"):
        rows.append(_event(len(rows), name, {}, runtime.call(name, {})))
        for change in runtime.after_call(name, {}):
            rows.append(_event(len(rows), WORLD_CHANGE, change, ""))
    write_state(run_dir / "state_after.json", runtime.service)
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return rows


def _run(world: str, trial: int = 1, **kwargs: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "world_id": world,
        "trial": trial,
        "run_status": "COMPLETED",
        "exit_code": 0,
        "duration_seconds": 0.1,
        "tool_calls": 1,
        "write_calls": 0,
        "violations": [],
        "outcome": "MET",
        "run_dir": f"runs/{world}/{trial}",
        "fixed_id": world,
    }
    values.update(kwargs)
    return values


def test_replay_reapplies_interferences_and_ignores_pseudo_events_as_calls(tmp_path: Path) -> None:
    scenario = _shifty()
    rows = _record_with_change(scenario, tmp_path / "runs" / "w" / "1")
    assert [r["name"] for r in rows] == ["read", WORLD_CHANGE, "bump"]
    outcome = replay_run(scenario, _run("w", outcome="NOT_MET"), tmp_path)
    assert outcome.reproduced, outcome.detail
    assert outcome.detail.startswith("2 calls re-executed")


def test_replay_detects_a_missing_or_invented_world_change(tmp_path: Path) -> None:
    scenario = _shifty()
    rows = _record_with_change(scenario, tmp_path / "runs" / "w" / "1")
    trace = tmp_path / "runs" / "w" / "1" / "trace.jsonl"
    original = trace.read_text(encoding="utf-8")
    without = [dict(r, index=i) for i, r in enumerate(r for r in rows if r["name"] != WORLD_CHANGE)]
    trace.write_text("\n".join(json.dumps(r) for r in without) + "\n", encoding="utf-8")
    assert "not recorded" in replay_run(scenario, _run("w", outcome="NOT_MET"), tmp_path).detail
    invented = [*rows, {**rows[1], "index": 3}]
    trace.write_text("\n".join(json.dumps(r) for r in invented) + "\n", encoding="utf-8")
    assert "does not replay" in replay_run(scenario, _run("w", outcome="NOT_MET"), tmp_path).detail
    trace.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    assert (
        "after the last call" in replay_run(scenario, _run("w", outcome="NOT_MET"), tmp_path).detail
    )
    trace.write_text(original, encoding="utf-8")


# --- report assembly -------------------------------------------------------------------------


def _results(
    booking: McpScenario,
    outcomes: dict[str, RunOutcome | None],
    *,
    status: str = "COMPLETED",
    violations: dict[str, str] | None = None,
) -> list[WorldResult]:
    worlds, _ = prepare_worlds(booking, "fixed", attempts=1, seed=0)
    results: list[WorldResult] = []
    for rw in worlds:
        result = WorldResult(rw)
        outcome = outcomes.get(rw.id) if rw.id in outcomes else outcomes.get("*")
        if outcome is not None:
            result.outcomes = [outcome]
            bad = outcome.violated or outcome.outcome is Outcome.NOT_MET
            result.runs = [
                _run(
                    rw.id,
                    run_status=status,
                    outcome=outcome.outcome.value if outcome.outcome else None,
                    violations=[{"invariant": violations[rw.id], "message": "cancelled"}]
                    if violations and rw.id in violations
                    else [],
                )
            ]
            if bad:
                result.example = _example()
                if violations and rw.id in violations:
                    result.violations = [(violations[rw.id], "cancelled")]
        results.append(result)
    return results


def _example() -> Any:
    from isitright.core.subjects import RunRecord
    from isitright.packs.mcp.runner import AgentRun

    return AgentRun(RunRecord(), {}, {}, [_cancel_event()], {})


def _report(booking: McpScenario, results: list[WorldResult]) -> CaseReport:
    audit = build_report(booking, "x:y", "agent", 1, results, {}, Budget(), 0.5)
    return audit.cases[0]


MET = RunOutcome(Outcome.MET)
NOT_MET = RunOutcome(Outcome.NOT_MET)


def test_clean_runs_with_working_controls(booking: McpScenario) -> None:
    case = _report(booking, _results(booking, {"*": MET}))
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert case.controls is not None and case.controls.status == "DISCRIMINATING"
    assert "DOMAIN_VALIDATED" in case.validity.tiers
    assert case.headline.startswith("No invariant violation")
    assert "control worlds behaved as expected" in case.headline
    assert case.attribution_status.value == "UNDETERMINED"


def test_an_invariant_violation_is_the_headline(booking: McpScenario) -> None:
    results = _results(
        booking,
        {"*": MET, "original": RunOutcome(Outcome.NOT_MET, violated=True)},
        violations={"original": "no_cancel_without_basis"},
    )
    case = _report(booking, results)
    assert case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert case.headline == (
        "Invariant 'no_cancel_without_basis' violated in 1 of 1 runs on world original "
        "(attribution not assessed)"
    )
    finding = next(f for f in case.findings if f.world_id == "original")
    assert {o.kind for o in finding.oracles} == {"INVARIANT", "REFERENCE_PROGRAM"}
    assert finding.stability is not None and finding.stability.world is not None
    assert finding.stability.world.violated == 1 and finding.stability.k == 1
    assert {w.id: w.counts["violated"] for w in case.worlds}["original"] == 1


def test_a_control_that_is_never_reached_does_not_discriminate(booking: McpScenario) -> None:
    case = _report(
        booking,
        _results(booking, {"*": MET, "booked_23h_59m": NOT_MET, "flight_cancelled": NOT_MET}),
    )
    assert case.controls is not None and case.controls.status == "NOT_DISCRIMINATING"
    assert case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert case.headline.startswith("Expected behavior not reached")


def test_no_completed_run_is_inconclusive_and_no_valid_world_is_unsupported(
    booking: McpScenario,
) -> None:
    timed_out = RunOutcome(None, error=True)
    inconclusive = _report(booking, _results(booking, {"*": timed_out}, status="TIMEOUT"))
    assert inconclusive.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert inconclusive.controls is not None and inconclusive.controls.status == "NOT_APPLICABLE"
    invalid = _tiny(fixed=[_fixed("bad", validate=lambda s: ["x"])])
    worlds, _ = prepare_worlds(invalid, "fixed", attempts=1, seed=0)
    results = [WorldResult(w) for w in worlds]
    for result in results:
        result.world.validity = result.world.validity.model_copy(update={"status": "INVALID"})
    unsupported = build_report(invalid, "x:y", "agent", 1, results, {}, Budget(), 0.1).cases[0]
    assert unsupported.divergence_status is DivergenceStatus.UNSUPPORTED
    assert unsupported.headline.startswith("Unsupported")


def test_without_control_worlds_the_headline_says_the_evidence_is_weak() -> None:
    scenario = _tiny(fixed=[_fixed("only")])
    worlds, _ = prepare_worlds(scenario, "fixed", attempts=1, seed=0)
    results = [WorldResult(w, [MET]) for w in worlds]
    case = build_report(scenario, "x:y", "agent", 1, results, {}, Budget(), 0.1).cases[0]
    assert case.controls is not None and case.controls.status == "NOT_APPLICABLE"
    assert case.headline.endswith("so this is weak evidence")


def test_headlines_never_use_the_banned_words(booking: McpScenario) -> None:
    violated = RunOutcome(Outcome.NOT_MET, violated=True)
    for outcomes in ({"original": violated}, {"booked_23h_59m": NOT_MET}, {"original": MET}):
        case = _report(
            booking, _results(booking, outcomes, violations={"original": "no_cancel_without_basis"})
        )
        words = case.headline.lower().replace("'", " ").split()
        assert not {"pass", "passed", "fail", "failed", "correct", "wrong"} & set(words)


def test_report_contract_rejects_inconsistent_statuses(booking: McpScenario) -> None:
    case = _report(booking, _results(booking, {"*": MET}))
    data = case.model_dump(mode="json")
    with pytest.raises(ValidationError, match="findings must agree"):
        CaseReport.model_validate({**data, "divergence_status": "COUNTEREXAMPLE_FOUND"})
    with pytest.raises(ValidationError, match="never says pass"):
        CaseReport.model_validate({**data, "headline": "The agent did not fail"})
    with pytest.raises(ValidationError, match="no executed worlds"):
        CaseReport.model_validate({**data, "divergence_status": "UNSUPPORTED"})


def test_report_validates_against_the_checked_in_schema(
    booking: McpScenario, tmp_path: Path
) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema == AuditReport.model_json_schema()
    audit = build_report(
        booking, "x:y", "agent", 1, _results(booking, {"*": MET}), {}, Budget(), 0.5
    )
    write_report(audit, tmp_path)
    Draft202012Validator(schema).validate(json.loads((tmp_path / "report.json").read_text("utf-8")))
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert audit.cases[0].headline in markdown and "not a verdict" in markdown


def test_a_rate_claim_is_never_made_below_adequate_evidence(booking: McpScenario) -> None:
    results = _results(booking, {"*": MET, "booked_23h_59m": NOT_MET})
    case = _report(booking, results)
    finding = next(f for f in case.findings if f.world_id == "booked_23h_59m")
    assert finding.stability is not None and finding.stability.rate_claim is None
    assert "counts only" in finding.stability.note


# --- replay of a recorded run --------------------------------------------------------------------


def _record(
    scenario: McpScenario, world_id: str, calls: list[tuple[str, dict[str, Any]]], run_dir: Path
) -> None:
    """Write the files the serving process would have written for these calls."""
    from isitright.packs.mcp.runtime import ServiceRuntime

    run_dir.mkdir(parents=True)
    world, interferences = world_of(scenario, scenario.fixed(world_id))
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    write_state(run_dir / "state_before.json", runtime.service)
    rows = []
    for index, (name, arguments) in enumerate(calls):
        try:
            result, is_error = runtime.call(name, arguments), False
        except Exception as error:
            result, is_error = str(error), True
        rows.append(
            {
                "index": index,
                "name": name,
                "arguments": arguments,
                "result": result,
                "is_error": is_error,
            }
        )
    write_state(run_dir / "state_after.json", runtime.service)
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")


def _recorded(booking: McpScenario, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    calls = [
        ("get_booking", {"booking_id": "B100"}),
        ("get_booking", {"booking_id": "NOPE"}),
        ("cancel_booking", {"booking_id": "B100"}),
    ]
    run_dir = tmp_path / "runs" / "booked_24h_01m" / "1"
    _record(booking, "booked_24h_01m", calls, run_dir)
    before = json.loads((run_dir / "state_before.json").read_text("utf-8"))
    after = json.loads((run_dir / "state_after.json").read_text("utf-8"))
    world, interferences = world_of(booking, booking.fixed("booked_24h_01m"))
    judgement = judge_run(
        booking,
        reference_outcome(booking, world, interferences),
        before,
        after,
        read_trace(run_dir / "trace.jsonl"),
    )
    run = _run(
        "booked_24h_01m",
        tool_calls=3,
        write_calls=1,
        outcome=judgement.outcome.value,
        violations=[{"invariant": n, "message": m} for n, m in judgement.violations],
    )
    return run, tmp_path


def test_replay_reproduces_a_recorded_run(booking: McpScenario, tmp_path: Path) -> None:
    run, output = _recorded(booking, tmp_path)
    assert run["violations"]  # the recorded run did violate the invariant
    outcome = replay_run(booking, run, output)
    assert outcome.reproduced, outcome.detail


def test_replay_detects_tampered_or_drifted_records(booking: McpScenario, tmp_path: Path) -> None:
    run, output = _recorded(booking, tmp_path)
    run_dir = output / "runs" / "booked_24h_01m" / "1"
    trace = run_dir / "trace.jsonl"
    original = trace.read_text(encoding="utf-8")
    trace.write_text(original.replace('"result": "{', '"result": "{x', 1), encoding="utf-8")
    assert "different result" in replay_run(booking, run, output).detail
    trace.write_text(original, encoding="utf-8")
    after = run_dir / "state_after.json"
    saved = after.read_text(encoding="utf-8")
    after.write_text(saved.replace("cancelled", "active"), encoding="utf-8")
    assert "final state differs" in replay_run(booking, run, output).detail
    after.write_text(saved, encoding="utf-8")
    assert (
        "invariant verdicts differ" in replay_run(booking, {**run, "violations": []}, output).detail
    )
    assert "oracle verdict differs" in replay_run(booking, {**run, "outcome": "MET"}, output).detail
    before = run_dir / "state_before.json"
    before.write_text(before.read_text("utf-8").replace("cust_1", "cust_2"), encoding="utf-8")
    assert "different starting state" in replay_run(booking, run, output).detail


def test_replay_notices_a_tool_that_no_longer_exists(booking: McpScenario, tmp_path: Path) -> None:
    run, output = _recorded(booking, tmp_path)
    trace = output / "runs/booked_24h_01m/1/trace.jsonl"
    trace.write_text(trace.read_text("utf-8").replace("get_booking", "get_booking_v2", 1), "utf-8")
    assert "different result" in replay_run(booking, run, output).detail


def test_replay_has_nothing_to_check_for_a_run_that_never_started_a_server(
    booking: McpScenario, tmp_path: Path
) -> None:
    run = _run("original", run_status="TIMEOUT", outcome=None)
    skipped = replay_run(booking, run, tmp_path)
    assert skipped.reproduced and "did not complete" in skipped.detail
    lost = replay_run(booking, _run("original"), tmp_path)
    assert not lost.reproduced and "missing" in lost.detail


def test_module_is_importable_without_the_mcp_sdk() -> None:
    """Declaring a scenario and generating worlds work in a process without the MCP SDK."""
    import subprocess

    code = (
        "import sys; sys.modules['mcp'] = None; import isitright.packs.mcp, "
        "isitright.packs.mcp.trace, isitright.packs.mcp.model, isitright.packs.mcp.generate; "
        "import isitright.cli; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.stdout.strip() == "ok", result.stderr


# --- the stack under test ------------------------------------------------------------------------


def _transcript(run_dir: Path, **overrides: Any) -> None:
    data: dict[str, Any] = {
        "provider": "anthropic",
        "model": "m1",
        "sdk_versions": {"mcp": "2.3.0", "anthropic": "0.50.0"},
        "settings": {"max_turns": 20, "temperature": None},
        "usage": [
            {"input_tokens": 100, "output_tokens": 10, "cost": 0.25},
            {"input_tokens": 150, "output_tokens": 20, "cost": 0.0},
        ],
        "stop_reason": "final",
    }
    data.update(overrides)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "transcript.json").write_text(json.dumps(data), encoding="utf-8")


def test_read_transcript_gives_the_subject_usage_and_cost(tmp_path: Path) -> None:
    _transcript(tmp_path)
    found = read_transcript(tmp_path, ("shop_agent", "sha256:abc"))
    subject = found["subject"]
    assert (subject["provider"], subject["model"]) == ("anthropic", "m1")
    assert (subject["harness_name"], subject["harness_version"]) == ("shop_agent", "sha256:abc")
    assert subject["sdk_versions"]["mcp"] == "2.3.0" and subject["settings"]["max_turns"] == 20
    assert (found["model_calls"], found["input_tokens"], found["output_tokens"]) == (2, 250, 30)
    assert found["money"] == 0.25 and found["agent_stop_reason"] == "final"
    # One call without a cost makes the total unknowable: no money is reported at all.
    _transcript(
        tmp_path,
        usage=[
            {"input_tokens": 1, "output_tokens": 1, "cost": 0.1},
            {"input_tokens": 1, "output_tokens": 1},
        ],
    )
    partial = read_transcript(tmp_path, (None, None))
    assert "money" not in partial and partial["input_tokens"] == 2


def test_read_transcript_tolerates_missing_malformed_or_partial_files(tmp_path: Path) -> None:
    assert read_transcript(tmp_path, (None, None)) == {}
    (tmp_path / "transcript.json").write_text("not json", encoding="utf-8")
    assert read_transcript(tmp_path, (None, None)) == {}
    (tmp_path / "transcript.json").write_text('{"model": "m"}', encoding="utf-8")
    assert read_transcript(tmp_path, (None, None)) == {}
    _transcript(tmp_path, usage=[{"input_tokens": "x"}], stop_reason="weird")
    found = read_transcript(tmp_path, (None, None))
    assert found["subject"]["model"] == "m1" and "input_tokens" not in found
    assert found["agent_stop_reason"] is None


def test_harness_identity_names_the_script_and_hashes_its_content(tmp_path: Path) -> None:
    script = tmp_path / "my_agent.py"
    script.write_text("print(1)\n", encoding="utf-8")
    name, version = harness_identity(["python", str(script)])
    assert name == "my_agent" and version is not None and version.startswith("sha256:")
    script.write_text("print(2)\n", encoding="utf-8")
    assert harness_identity(["python", str(script)])[1] != version
    assert harness_identity(["some-binary", "--flag"]) == (None, None)


def _with_subject(results: list[WorldResult], models: list[str]) -> None:
    runs = [run for r in results for run in r.runs]
    for run, model in zip(runs, models, strict=False):
        run["subject"] = {"provider": "p", "model": model}


def test_a_single_subject_is_reported_and_a_mixed_set_is_kept_per_run(booking: McpScenario) -> None:
    one = _results(booking, {"*": MET})
    _with_subject(one, ["m1"] * 5)
    assert _report(booking, one).extensions["mcp"]["subject"] == {"provider": "p", "model": "m1"}
    mixed = _results(booking, {"*": MET})
    _with_subject(mixed, ["m1", "m2"])
    case = _report(booking, mixed)
    assert case.extensions["mcp"]["subject"] is None
    assert {r["subject"]["model"] for r in case.extensions["mcp"]["runs"] if r.get("subject")} == {
        "m1",
        "m2",
    }
    assert _report(booking, _results(booking, {"*": MET})).extensions["mcp"]["subject"] is None


_ = RunWorld
