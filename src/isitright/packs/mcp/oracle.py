"""Roles and judgements: the scenario's reference procedure and invariants applied to any world.

The reference procedure runs in-process on the world. If it makes a write, acting is right and the
world is a *control*; if it does nothing, the world is a *trap*. An agent run meets the oracle
when its final service state equals the one the reference procedure leaves (after the scenario's
normalization). Invariants are checked on every run. A world outside the oracle's stated
assumptions is reported as `CANNOT_JUDGE`, never scored silently.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from isitright.core.mutations import World
from isitright.core.oracles import Judgement, Outcome, Role
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    Interference,
    McpScenario,
    ServiceState,
    TraceDict,
)
from isitright.packs.mcp.runtime import RuntimeCaller, ServiceRuntime


class EvaluationError(RuntimeError):
    """A scenario's own invariant raised, which is a scenario bug, not a finding."""


@dataclass
class Reference:
    role: Role
    basis: str
    after: ServiceState | None
    writes: int
    unjudgeable: str | None = None
    write_calls: tuple[str, ...] = ()
    """The reference's successful write calls, normalized and sorted."""


def reference_outcome(
    scenario: McpScenario, world: World, interferences: tuple[Interference, ...] = ()
) -> Reference:
    """Run the reference procedure on a fresh runtime of the world."""
    reason = scenario.oracle.judgeable(world)
    if reason is not None:
        return Reference(Role.UNJUDGEABLE, reason, None, 0, reason)
    if scenario.external is not None:
        return external_reference(scenario, world)
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    caller = RuntimeCaller(runtime)
    try:
        scenario.oracle.reference(caller)
    except Exception as error:  # the reference itself failed: that is a statement about the oracle
        reason = f"the reference procedure raised {type(error).__name__}: {error}"
        return Reference(Role.UNJUDGEABLE, reason, None, 0, reason)
    calls = successful_writes(scenario, caller.trace)
    writes = len(calls)
    if writes:
        basis = f"the reference procedure made {writes} write call(s): acting is right"
        return Reference(Role.CONTROL, basis, runtime.service, writes, None, calls)
    return Reference(Role.TRAP, "the reference procedure changed nothing", runtime.service, 0)


def external_reference(scenario: McpScenario, world: World) -> Reference:
    """The reference procedure, run against the third-party server on a copy of the world."""
    import tempfile
    from pathlib import Path

    from isitright.packs.mcp.external import ExternalCaller
    from isitright.packs.mcp.session import McpSession

    external = scenario.external
    with tempfile.TemporaryDirectory(prefix="isitright-ext-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        parameters = external.parameters(scenario.layout.to_service(world.state), directory)
        session = McpSession(parameters)
        caller = ExternalCaller(session)
        try:
            scenario.oracle.reference(caller)
        except Exception as error:  # the reference failed: a statement about the oracle
            reason = f"the reference procedure raised {type(error).__name__}: {error}"
            return Reference(Role.UNJUDGEABLE, reason, None, 0, reason)
        finally:
            session.close()
        after = external.adapter.read(directory)
    calls = successful_writes(scenario, caller.trace)
    if calls:
        basis = f"the reference procedure made {len(calls)} write call(s): acting is right"
        return Reference(Role.CONTROL, basis, after, len(calls), None, calls)
    return Reference(Role.TRAP, "the reference procedure changed nothing", after, 0)


def successful_writes(scenario: McpScenario, trace: list[TraceDict]) -> tuple[str, ...]:
    """Normalized, sorted successful write calls of a trace."""
    return tuple(
        sorted(
            json.dumps(
                scenario.oracle.normalize_call(event["name"], event["arguments"]),
                sort_keys=True,
                default=str,
            )
            for event in trace
            if event["name"] != WORLD_CHANGE
            and not event["is_error"]
            and (tool := scenario.tool(event["name"])) is not None
            and tool.writes
        )
    )


def judge_run(
    scenario: McpScenario,
    reference: Reference,
    before: ServiceState,
    after: ServiceState,
    trace: list[TraceDict],
) -> Judgement:
    """Invariants on copies of the record, and the comparison with the reference outcome."""
    violations: list[tuple[str, str]] = []
    for invariant in scenario.oracle.invariants:
        try:
            messages = invariant.check(
                copy.deepcopy(before), copy.deepcopy(after), copy.deepcopy(trace)
            )
        except Exception as error:
            raise EvaluationError(f"scenario check {invariant.name!r} raised: {error}") from error
        violations.extend((invariant.name, message) for message in messages)
    if reference.after is None:
        return Judgement(
            Outcome.CANNOT_JUDGE, [reference.unjudgeable or "no reference outcome"], violations
        )
    same = (
        scenario.oracle.normalize(after) == scenario.oracle.normalize(reference.after)
        and successful_writes(scenario, trace) == reference.write_calls
    )
    return Judgement(
        Outcome.MET if same else Outcome.NOT_MET,
        [] if same else [f"expected behavior not reached: {scenario.oracle.description}"],
        violations,
    )
