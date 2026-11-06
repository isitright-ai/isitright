"""Which worlds to run live, in what order, and when to stop.

A live run costs money and time, and most generated worlds tell us nothing. A pack screens each
world without the agent (replaying a recorded trace, or a recorded program) and gives it a class:

* ``WRONG_IF_UNCHANGED``: the recorded behavior replays identically and the oracle says it is now
  wrong. Highest priority.
* ``STALE``: the recorded behavior cannot be replayed on this world (a response the agent saw
  differs). Run live at normal priority.
* ``RIGHT_IF_UNCHANGED``: the recorded behavior still satisfies the oracle. Lowest priority; a
  world the budget did not reach is listed as not run, never as passing.
* ``UNSCREENABLE``: no usable baseline, or the oracle cannot judge the world.

Screening is a ranking, not a verdict. Within a class worlds are ordered by expected information,
the feature-coverage score used as a greedy order, deterministic for a seed. The stopping rules
are counts on the worlds that were run: a stratum (family chain, target chain, role) stops after a
stated number of worlds without a finding, and the run stops after a stated number of consecutive
worlds that added no uncovered feature and no finding.

Any pack's world type works if it has ``id``, ``world`` (a `World`), ``role`` and ``observable``.
"""

from __future__ import annotations

import heapq
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, TypeVar

from isitright.core.evidence import StoppingRecord, StratumRecord
from isitright.core.mutations import World
from isitright.core.oracles import Role


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


class Rankable(Protocol):
    id: str
    world: World
    role: Role
    observable: bool


W = TypeVar("W", bound=Rankable)
Feature = tuple[str, str, str]


def features_of(w: Rankable) -> frozenset[Feature]:
    """What a world exercises: per mutation, family and touched field, hints, atoms and edit kinds,
    each in the world's role. The greedy coverage order and the stopping rule both read this."""
    found: set[Feature] = set()
    for m in w.world.path:
        role = w.role.value
        for touched in m.touches or [""]:
            found.add((m.family, touched, role))
        found.add((m.family, "hints:" + "+".join(sorted(m.hints)), role))
        for collection, key in m.atoms:
            found.add((m.family, f"atom:{collection}:{key}", role))
        found.add((m.family, "edits:" + "+".join(sorted({e.op for e in m.edits})), role))
    return frozenset(found)


def interleave(singles: list[W], composed: list[W]) -> list[W]:
    """Priority order: three single mutations, then one composition, so a run stopped early by a
    budget has still seen both kinds."""
    out: list[W] = []
    s, c = iter(singles), iter(composed)
    while len(out) < len(singles) + len(composed):
        out.extend(w for _, w in zip(range(3), s, strict=False))
        out.extend(w for _, w in zip(range(1), c, strict=False))
    return out


def greedy_cover(
    keyed: list[tuple[W, frozenset[Feature]]], cap: int
) -> tuple[list[W], set[Feature]]:
    """Greedy cover, lazily: a world's gain only shrinks, so a stale gain on the heap is an upper
    bound and a world is taken when its refreshed gain still leads. Same picks as scanning every
    world each step, in O(n log n) for the usual case."""
    chosen: list[W] = []
    covered: set[Feature] = set()
    ever: set[Feature] = set()
    cap = min(cap, len(keyed))
    heap = [(-len(f), i) for i, (_, f) in enumerate(keyed)]
    heapq.heapify(heap)
    cleared = False
    while len(chosen) < cap and heap:
        negative, index = heapq.heappop(heap)
        world, features = keyed[index]
        gain = len(features - covered)
        if gain != -negative:
            heapq.heappush(heap, (-gain, index))
            continue
        if gain == 0 and not cleared:
            # everything left adds nothing: start another round with the covered set cleared
            covered.clear()
            cleared = True
            heap = [(-len(keyed[i][1]), i) for _, i in [*heap, (negative, index)]]
            heapq.heapify(heap)
            continue
        cleared = False
        chosen.append(world)
        covered |= features
        ever |= features
    return chosen, ever


def coverage_order(worlds: list[W], limit: int | None = None) -> list[W]:
    """Worlds in the 0.4 coverage order: greedy on uncovered features (three single mutations to
    one composition), earlier visiting order breaking ties. ``limit`` caps the length."""
    keyed = [(w, features_of(w)) for w in worlds]
    cap = len(keyed) if limit is None else min(limit, len(keyed))
    composed_cap = cap // 4 if limit is not None else cap
    single = [(w, f) for w, f in keyed if len(w.world.path) <= 1]
    composed = [(w, f) for w, f in keyed if len(w.world.path) > 1]
    chosen_single, _ = greedy_cover(single, cap - min(composed_cap, len(composed)))
    chosen_composed, _ = greedy_cover(composed, cap - len(chosen_single))
    return interleave(chosen_single, chosen_composed)


def eligible(worlds: Sequence[W]) -> list[W]:
    """Worlds a live run can say something about: judgeable by the oracle and observable."""
    return [w for w in worlds if w.role is not Role.UNJUDGEABLE and w.observable]


def stratum_of(world: Rankable) -> tuple[str, str, str]:
    path = world.world.path
    return (
        "+".join(m.family for m in path) or "baseline",
        "+".join(m.target for m in path) or "state",
        world.role.value,
    )


def rank_worlds(
    worlds: Sequence[W],
    screens: dict[str, Screened] | None,
    *,
    mode: Ranking = "screening",
    seed: int = 0,
) -> list[W]:
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
    out: list[W] = []
    for priority in sorted(set(PRIORITY.values())):
        part = [w for w in pool if PRIORITY[screens[w.id].cls] == priority]
        out.extend(coverage_order(part))
    return out


def _diverse(pool: list[W], screens: dict[str, Screened]) -> list[W]:
    """Breadth before depth: the best world of every stratum first, then the second best of every
    stratum, and so on. Within a stratum and within a round, screening class decides, then the
    coverage order. Worlds of one stratum tend to say the same thing, so a second look at a
    stratum comes after a first look at the others."""
    position = {w.id: i for i, w in enumerate(coverage_order(pool))}
    groups: dict[tuple[str, str, str], list[W]] = {}
    for w in pool:
        groups.setdefault(stratum_of(w), []).append(w)

    def key(w: W) -> tuple[int, int]:
        return PRIORITY[screens[w.id].cls], position[w.id]

    for members in groups.values():
        members.sort(key=key)
    out: list[W] = []
    depth = 0
    while True:
        layer = [m[depth] for m in groups.values() if len(m) > depth]
        if not layer:
            return out
        out.extend(sorted(layer, key=key))
        depth += 1


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
    universe: Sequence[Rankable]
    strata: dict[tuple[str, str, str], _Stratum] = field(default_factory=dict)
    covered: set[Feature] = field(default_factory=set)
    quiet: int = 0
    run_stopped: str | None = None

    def __post_init__(self) -> None:
        for world in self.universe:
            self.strata.setdefault(stratum_of(world), _Stratum()).total += 1

    def skip_reason(self, world: Rankable) -> str | None:
        """Why this world is not run, or None to run it."""
        if self.run_stopped:
            return self.run_stopped
        s = self.strata.setdefault(stratum_of(world), _Stratum())
        if s.stopped:
            return self._stratum_reason(stratum_of(world), s)
        return None

    def record(self, world: Rankable, found: bool) -> None:
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
