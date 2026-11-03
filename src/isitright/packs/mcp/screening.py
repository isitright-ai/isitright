"""Screening without the agent, ranking, and the stopping rules.

A live run costs money and time, and most generated worlds tell us nothing. Screening replays the
agent's recorded baseline trace against a candidate world's service and runs the oracle, with no
agent involved:

* ``STALE``: some response the agent saw differs from the recorded one, so the recorded behavior
  says nothing about what the agent would do in this world. Run live at normal priority.
* ``WRONG_IF_UNCHANGED``: the trace replays identically and the oracle says the old behavior is now
  wrong. Highest priority.
* ``RIGHT_IF_UNCHANGED``: the trace replays identically and the oracle is satisfied. Lowest
  priority; a world the budget did not reach is listed as not run, never as passing.
* ``UNSCREENABLE``: no usable baseline trace, or the oracle cannot judge the world.

Screening is a ranking, not a verdict. It never removes a world from the report. The ranking and the
stopping rules are not specific to MCP and live in `isitright.core.selection`; this module screens
a world against the recorded trace and re-exports them.
"""

from __future__ import annotations

from collections.abc import Sequence

from isitright.core.oracles import Outcome, Role
from isitright.core.selection import (
    PRIORITY,
    Ranking,
    Screened,
    ScreeningClass,
    StoppingRules,
    StopState,
    eligible,
    rank_worlds,
    stratum_of,
)
from isitright.packs.mcp.generate import GeneratedWorld
from isitright.packs.mcp.model import McpScenario, TraceDict
from isitright.packs.mcp.oracle import judge_run
from isitright.packs.mcp.replay import replay_events
from isitright.packs.mcp.runtime import ServiceRuntime

rank = rank_worlds
__all__ = [
    "PRIORITY",
    "Ranking",
    "Screened",
    "ScreeningClass",
    "StopState",
    "StoppingRules",
    "eligible",
    "rank",
    "screen_all",
    "screen_world",
    "stratum_of",
]


def screen_world(
    scenario: McpScenario, generated: GeneratedWorld, baseline: Sequence[TraceDict] | None
) -> Screened:
    """Classify one generated world against the baseline trace."""
    if baseline is None:
        return Screened(ScreeningClass.UNSCREENABLE, "no usable baseline trace")
    if scenario.external is not None:
        return Screened(
            ScreeningClass.UNSCREENABLE,
            "an external server has no in-process service to replay the trace on",
        )
    if generated.role is Role.UNJUDGEABLE:
        return Screened(
            ScreeningClass.UNSCREENABLE,
            f"the oracle cannot judge this world: {generated.role_basis}",
        )
    if not generated.observable:
        return Screened(ScreeningClass.UNSCREENABLE, "the change is unobservable to the agent")
    events = [dict(e) for e in baseline]
    try:
        ok, detail, final = replay_events(scenario, generated.world, (), events)
    except Exception as error:  # a timer that cannot apply in this world: screening cannot say
        return Screened(ScreeningClass.UNSCREENABLE, f"the replay raised {type(error).__name__}")
    if not ok or final is None:
        return Screened(ScreeningClass.STALE, detail)
    start = ServiceRuntime.for_world(scenario, generated.world).service
    judgement = judge_run(scenario, generated.reference, start, final, events)
    if judgement.outcome is Outcome.CANNOT_JUDGE:
        return Screened(ScreeningClass.UNSCREENABLE, "the oracle cannot judge the replayed run")
    if judgement.violations or judgement.outcome is Outcome.NOT_MET:
        return Screened(
            ScreeningClass.WRONG_IF_UNCHANGED,
            "the recorded calls replay identically and the oracle says they are now wrong",
        )
    return Screened(
        ScreeningClass.RIGHT_IF_UNCHANGED,
        "the recorded calls replay identically and the oracle is satisfied",
    )


def screen_all(
    scenario: McpScenario, worlds: Sequence[GeneratedWorld], baseline: Sequence[TraceDict] | None
) -> dict[str, Screened]:
    return {w.id: screen_world(scenario, w, baseline) for w in worlds}
