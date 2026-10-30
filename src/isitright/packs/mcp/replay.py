"""Replay recorded agent runs offline: no agent, no MCP, no network.

A run is reproduced when re-executing its recorded tool calls against a freshly built world gives
the same results and final state, and the invariants and the oracle then give the same verdicts as
recorded. This depends on scenario handlers being deterministic given state and arguments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isitright.core.evidence import AuditReport, EvalCase
from isitright.core.mutations import World
from isitright.core.oracles import Outcome
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    McpScenario,
    ScenarioError,
    TraceDict,
    load_scenario,
)
from isitright.packs.mcp.oracle import judge_run, reference_outcome
from isitright.packs.mcp.runner import read_state, read_trace
from isitright.packs.mcp.serve import world_of


@dataclass(frozen=True)
class ReplayOutcome:
    world_id: str
    trial: int
    reproduced: bool
    detail: str


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _world(scenario: McpScenario, run: dict[str, Any], run_dir: Path) -> Any:
    if run.get("fixed_id"):
        return world_of(scenario, scenario.fixed(run["fixed_id"]))
    return World.from_json(json.loads((run_dir / "world.json").read_text(encoding="utf-8"))), ()


def replay_events(
    scenario: McpScenario,
    world: World,
    interferences: Any,
    events: list[TraceDict],
) -> tuple[bool, str, dict[str, Any] | None]:
    """Re-execute the calls; returns (ok, detail, final service state)."""
    from isitright.packs.mcp.runtime import ServiceRuntime

    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    expected_changes: list[dict[str, Any]] = []
    for event in events:
        if event["name"] == WORLD_CHANGE:
            if not expected_changes or expected_changes.pop(0) != event["arguments"]:
                return False, f"call {event['index']} is a world change that does not replay", None
            continue
        if expected_changes:
            return (
                False,
                f"call {event['index']} follows a world change that was not recorded",
                None,
            )
        try:
            result, is_error = runtime.call(event["name"], event["arguments"]), False
        except Exception as error:
            result, is_error = str(error), True
        if (result, is_error) != (event["result"], event["is_error"]):
            return False, f"call {event['index']} ({event['name']}) gave a different result", None
        if not is_error:
            expected_changes = runtime.after_call(event["name"], event["arguments"])
    if expected_changes:
        return False, "a world change was expected after the last call but not recorded", None
    return True, "", runtime.service


def replay_run(scenario: McpScenario, run: dict[str, Any], output_dir: Path) -> ReplayOutcome:
    run_dir = output_dir / run["run_dir"]

    def outcome(ok: bool, detail: str) -> ReplayOutcome:
        return ReplayOutcome(run["world_id"], run["trial"], ok, detail)

    if not (run_dir / "state_before.json").is_file():
        if run["run_status"] != "COMPLETED":
            return outcome(True, "the run did not complete; nothing was recorded to replay")
        return outcome(False, "the recorded state files are missing")
    world, interferences = _world(scenario, run, run_dir)
    events = read_trace(run_dir / "trace.jsonl")

    from isitright.packs.mcp.runtime import ServiceRuntime

    start = ServiceRuntime.for_world(scenario, world, interferences).service
    if _canonical(start) != _canonical(read_state(run_dir / "state_before.json")):
        return outcome(False, "the world now builds a different starting state than was recorded")
    ok, detail, final = replay_events(scenario, world, interferences, events)
    if not ok or final is None:
        return outcome(False, detail)
    if _canonical(final) != _canonical(read_state(run_dir / "state_after.json")):
        return outcome(False, "the replayed final state differs from the recorded one")
    reference = reference_outcome(scenario, world, interferences)
    judgement = judge_run(scenario, reference, start, final, events)
    recorded = sorted((v["invariant"], v["message"]) for v in run["violations"])
    if sorted(judgement.violations) != recorded:
        return outcome(False, "invariant verdicts differ from the recorded ones")
    if run["run_status"] == "COMPLETED" and judgement.outcome.value != run["outcome"]:
        return outcome(False, "the oracle verdict differs from the recorded one")
    calls = sum(1 for e in events if e["name"] != WORLD_CHANGE)
    return outcome(True, f"{calls} calls re-executed; state and verdicts match")


def replay_report(
    report: AuditReport,
    scenario: McpScenario | None,
    output_dir: Path,
    *,
    findings_only: bool = False,
) -> list[ReplayOutcome]:
    """Replay every run in the report (or only the runs behind a finding)."""
    case = report.cases[0]
    mcp = case.extensions["mcp"]
    scenario = scenario or load_scenario(mcp["scenario_ref"])
    affected = {f.divergence["example_run_dir"] for f in case.findings}
    runs = [r for r in mcp["runs"] if not findings_only or r["run_dir"] in affected]
    return [replay_run(scenario, run, output_dir) for run in runs]


def rerun_eval_case(case: EvalCase, scenario: McpScenario | None = None) -> dict[str, Any]:
    """Replay an exported case offline and re-judge it; `reproduced` means the same disagreement."""
    payload = case.payload
    try:
        scenario = scenario or load_scenario(payload["scenario_ref"])
    except ScenarioError as error:  # pragma: no cover - a stale reference
        return {"reproduced": False, "detail": str(error)}
    if payload.get("fixed_id"):
        world, interferences = world_of(scenario, scenario.fixed(payload["fixed_id"]))
    else:
        world, interferences = World.from_json(payload["world"]), ()
    ok, detail, final = replay_events(scenario, world, interferences, payload["trace"])
    if not ok or final is None:
        return {"reproduced": False, "detail": detail}
    from isitright.packs.mcp.runtime import ServiceRuntime

    before = ServiceRuntime.for_world(scenario, world, interferences).service
    judgement = judge_run(
        scenario,
        reference_outcome(scenario, world, interferences),
        before,
        final,
        payload["trace"],
    )
    expected = case.expectation["disagreement"]
    same = sorted({n for n, _ in judgement.violations}) == sorted(set(expected["violations"])) and (
        judgement.outcome.value == expected["outcome"]
    )
    disagrees = bool(judgement.violations) or judgement.outcome is Outcome.NOT_MET
    return {
        "reproduced": same and disagrees,
        "detail": detail or "replayed",
        "judgement": judgement.outcome.value,
    }
