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

Screening is a ranking, not a verdict. It never removes a world from the report. Within a class,
worlds are ordered by expected information, which is the 0.4 feature-coverage score used as a
greedy order, deterministic for a seed.

The stopping rules are counts on the worlds that were run: a stratum (family chain, target chain,
role) stops after a stated number of worlds without a finding, and the run stops after a stated
number of consecutive worlds that added no uncovered feature and no finding. A stopped stratum or
run is reported as "no finding in n of m worlds" with the reason.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from isitright.core.evidence import StoppingRecord, StratumRecord
from isitright.core.oracles import Outcome, Role
from isitright.packs.mcp.generate import GeneratedWorld, coverage_order, features_of
from isitright.packs.mcp.model import McpScenario, TraceDict
from isitright.packs.mcp.oracle import judge_run
from isitright.packs.mcp.replay import replay_events
from isitright.packs.mcp.runtime import ServiceRuntime


class ScreeningClass(StrEnum):
    WRONG_IF_UNCHANGED = "WRONG_IF_UNCHANGED"
    STALE = "STALE"
    RIGHT_IF_UNCHANGED = "RIGHT_IF_UNCHANGED"
    UNSCREENABLE = "UNSCREENABLE"


PRIORITY = {
    ScreeningClass.WRONG_IF_UNCHANGED: 0,
    ScreeningClass.STALE: 1,
    ScreeningClass.UNSCREENABLE: 1,
    ScreeningClass.RIGHT_IF_UNCHANGED: 2,
}
Ranking = Literal["screening", "diverse", "coverage", "random"]
"""``diverse`` (the default): screening class decides within each stratum and the strata take turns.
``screening``: strict class order, then coverage. ``coverage``: the 0.4 order. ``random``."""


@dataclass(frozen=True)
class Screened:
    cls: ScreeningClass
    basis: str


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


def eligible(worlds: Sequence[GeneratedWorld]) -> list[GeneratedWorld]:
    """Worlds a live run can say something about: judgeable by the oracle and observable."""
    return [w for w in worlds if w.role is not Role.UNJUDGEABLE and w.observable]


def rank(
    worlds: Sequence[GeneratedWorld],
    screens: dict[str, Screened] | None,
    *,
    mode: Ranking = "screening",
    seed: int = 0,
) -> list[GeneratedWorld]:
    """Eligible worlds in the order a run should visit them. Deterministic for a seed."""
    pool = eligible(worlds)
    if mode == "random":
        shuffled = list(pool)
        random.Random(seed).shuffle(shuffled)
        return shuffled
    if mode == "coverage" or screens is None:
        return coverage_order(pool)
    if mode == "diverse":
        return _diverse(pool, screens)
    out: list[GeneratedWorld] = []
    for priority in sorted(set(PRIORITY.values())):
        part = [w for w in pool if PRIORITY[screens[w.id].cls] == priority]
        out.extend(coverage_order(part))
    return out


def _diverse(pool: list[GeneratedWorld], screens: dict[str, Screened]) -> list[GeneratedWorld]:
    """Breadth before depth: the best world of every stratum first, then the second best of every
    stratum, and so on. Within a stratum and within a round, screening class decides, then the
    coverage order. Worlds of one stratum tend to say the same thing, so a second look at a
    stratum comes after a first look at the others."""
    position = {w.id: i for i, w in enumerate(coverage_order(pool))}
    groups: dict[tuple[str, str, str], list[GeneratedWorld]] = {}
    for w in pool:
        groups.setdefault(stratum_of(w), []).append(w)

    def key(w: GeneratedWorld) -> tuple[int, int]:
        return PRIORITY[screens[w.id].cls], position[w.id]

    for members in groups.values():
        members.sort(key=key)
    out: list[GeneratedWorld] = []
    depth = 0
    while True:
        layer = [m[depth] for m in groups.values() if len(m) > depth]
        if not layer:
            return out
        out.extend(sorted(layer, key=key))
        depth += 1


def stratum_of(world: GeneratedWorld) -> tuple[str, str, str]:
    path = world.world.path
    return (
        "+".join(m.family for m in path) or "baseline",
        "+".join(m.target for m in path) or "state",
        world.role.value,
    )


@dataclass
class StoppingRules:
    stratum_patience: int | None = 10
    """Stop a stratum after this many worlds run without a finding (None: never)."""
    run_patience: int | None = 30
    """Stop the run after this many consecutive worlds with no uncovered feature and no finding."""


@dataclass
class _Stratum:
    total: int = 0
    run: int = 0
    findings: int = 0
    since_finding: int = 0
    stopped: bool = False


@dataclass
class StopState:
    """Tracks the stopping rules while worlds are run in rank order."""

    rules: StoppingRules
    universe: Sequence[GeneratedWorld]
    strata: dict[tuple[str, str, str], _Stratum] = field(default_factory=dict)
    covered: set[tuple[str, str, str]] = field(default_factory=set)
    quiet: int = 0
    run_stopped: str | None = None

    def __post_init__(self) -> None:
        for world in self.universe:
            self.strata.setdefault(stratum_of(world), _Stratum()).total += 1

    def skip_reason(self, world: GeneratedWorld) -> str | None:
        """Why this world is not run, or None to run it."""
        if self.run_stopped:
            return self.run_stopped
        s = self.strata.setdefault(stratum_of(world), _Stratum())
        if s.stopped:
            return self._stratum_reason(stratum_of(world), s)
        return None

    def record(self, world: GeneratedWorld, found: bool) -> None:
        key = stratum_of(world)
        s = self.strata.setdefault(key, _Stratum())  # a named world outside the universe
        s.run += 1
        if found:
            s.findings += 1
            s.since_finding = 0
        else:
            s.since_finding += 1
        patience = self.rules.stratum_patience
        if patience is not None and s.since_finding >= patience and s.run < s.total:
            s.stopped = True
        features = features_of(world)
        new = not features <= self.covered
        self.covered |= features
        self.quiet = 0 if (new or found) else self.quiet + 1
        limit = self.rules.run_patience
        if limit is not None and self.quiet >= limit:
            self.run_stopped = (
                f"run stopped: {self.quiet} consecutive worlds added no uncovered feature and "
                "no finding"
            )

    def _stratum_reason(self, key: tuple[str, str, str], s: _Stratum) -> str:
        return (
            f"stratum stopped: no finding in {s.run} of {s.total} worlds of "
            f"{key[0]} / {key[1]} / {key[2]} (stratum rule: {self.rules.stratum_patience} "
            "worlds without a finding)"
        )

    def record_budget(self, exhausted: str | None) -> None:
        if exhausted and not self.run_stopped:
            self.run_stopped = f"{exhausted} budget exhausted"

    def to_record(self, budget_reason: str | None) -> StoppingRecord:
        rows = []
        for (family, target, role), s in sorted(self.strata.items()):
            if s.run == 0 and not s.stopped and s.total == 0:
                continue
            not_run = max(0, s.total - s.run)
            reason: str | None = None
            if s.stopped:
                reason = f"stratum rule: {self.rules.stratum_patience} worlds without a finding"
            elif not_run and self.run_stopped:
                reason = self.run_stopped
            elif not_run and budget_reason:
                reason = f"{budget_reason} budget exhausted"
            rows.append(
                StratumRecord(
                    family=family,
                    target=target,
                    role=role,
                    worlds_total=s.total,
                    worlds_run=s.run,
                    worlds_not_run=not_run,
                    with_findings=s.findings,
                    stopped=bool(s.stopped or (not_run and (self.run_stopped or budget_reason))),
                    stop_reason=reason,
                    summary=(
                        f"{'no finding' if not s.findings else f'{s.findings} with findings'} in "
                        f"{s.run} of {s.total} worlds" + (f": {reason}" if reason else "")
                    ),
                )
            )
        return StoppingRecord(
            stratum_patience=self.rules.stratum_patience,
            run_patience=self.rules.run_patience,
            run_stop_reason=self.run_stopped
            or (f"{budget_reason} budget exhausted" if budget_reason else None),
            strata=rows,
        )
