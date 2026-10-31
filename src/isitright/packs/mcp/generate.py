"""Generate a scenario's worlds with the core's families and annotate each one.

Every generated world carries its validity tiers, whether an agent could see the change at all, its
role from the reference procedure, and the mutation path with the hints behind it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from isitright.core.constraints import Validity, ValidityStatus, ValidityTier
from isitright.core.families import default_mutators
from isitright.core.hints import lookup_matches
from isitright.core.mutations import Candidate, Mutation, World
from isitright.core.oracles import Role
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.stochastic import Budget
from isitright.packs.mcp.model import McpScenario
from isitright.packs.mcp.oracle import Reference, reference_outcome


@dataclass
class GeneratedWorld:
    id: str
    world: World
    tiers: list[str]
    observable: bool
    role: Role
    role_basis: str
    unjudgeable: str | None
    group: str
    depth: int
    reference: Reference
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def families(self) -> list[str]:
        return [m.family for m in self.world.path]

    @property
    def description(self) -> str:
        return "; ".join(m.description for m in self.world.path) or "the unmutated baseline"


def observable(scenario: McpScenario, path: tuple[Mutation, ...]) -> bool:
    """Whether some change in the path can be seen by the agent through any read tool."""
    exposed = scenario.spec.exposed_paths()
    for mutation in path:
        if mutation.target in ("response", "timing"):
            return True
        for touched in mutation.touches:
            if touched.startswith("params."):
                return True
            if touched.endswith(".*"):
                if any(p.startswith(touched[:-1]) for p in exposed):
                    return True
            elif touched in exposed:
                return True
    return not path


def task_consistent(scenario: McpScenario, world: World) -> bool:
    """The task's story still holds: each lookup hint finds someone."""
    lookups = scenario.hints.of("lookup")
    return all(lookup_matches(world.state, hint) for hint in lookups)


def annotate(
    scenario: McpScenario, world: World, validity: Validity, world_id: str, group: str, depth: int
) -> GeneratedWorld:
    tiers = [t.value for t in validity.tiers]
    if task_consistent(scenario, world):
        tiers.append(ValidityTier.TASK_CONSISTENT.value)
    seen = observable(scenario, world.path)
    if seen:
        tiers.append(ValidityTier.OBSERVABLE.value)
    state_steps = [m for m in world.path if m.target == "state"]
    if state_steps and all(m.reachable for m in state_steps):
        tiers.append(ValidityTier.REACHABLE.value)
    reference = reference_outcome(scenario, world)
    return GeneratedWorld(
        world_id,
        world,
        tiers,
        seen,
        reference.role,
        reference.basis,
        reference.unjudgeable,
        group,
        depth,
        reference,
        notes=list(validity.notes),
    )


def generate_worlds(
    scenario: McpScenario,
    *,
    attempts: int = 20_000,
    seed: int = 0,
    depth: int = 2,
) -> tuple[list[GeneratedWorld], SearchResult]:
    """All valid worlds within the attempt budget (the baseline excluded), in visiting order."""
    found: list[GeneratedWorld] = []

    def collect(candidate: Candidate, validity: Validity) -> Evaluation:
        if validity.status is not ValidityStatus.VALID:  # pragma: no cover - search filters these
            return Evaluation(Verdict.REJECTED)
        path = candidate.world.path
        world_id = f"g{len(found) + 1:04d}_" + "+".join(m.family for m in path)
        found.append(
            annotate(
                scenario, candidate.world, validity, world_id, candidate.group, candidate.depth
            )
        )
        return Evaluation(Verdict.DISAGREE, validity)

    result = search(
        scenario.spec,
        World(scenario.base),
        scenario.hints,
        default_mutators(),
        collect,
        budget=Budget(attempts=attempts),
        seed=seed,
        depth=depth,
        stop_on_first=False,
        compose_from="all",
        max_parents=300,
    )
    return found, result


def select_worlds(
    worlds: list[GeneratedWorld], limit: int | None
) -> tuple[list[GeneratedWorld], dict[str, Any]]:
    """Pick at most ``limit`` worlds that cover the most distinct (family, target, role) features.

    The result is in priority order, so a run stopped early by a budget keeps the most informative
    worlds. Only worlds the oracle can judge and the agent can observe are eligible. Greedy: each
    step takes the world with the most uncovered features, earlier visiting order breaking ties;
    when every feature is covered the covered set is cleared for another round. Single mutations
    fill three quarters of the limit and compositions the rest. The totals say how much was left
    out, so a small run is never mistaken for an exhaustive one.
    """
    eligible = [w for w in worlds if w.role is not Role.UNJUDGEABLE and w.observable]

    def features(w: GeneratedWorld) -> frozenset[tuple[str, str, str]]:
        found: set[tuple[str, str, str]] = set()
        for m in w.world.path:
            role = w.role.value
            for touched in m.touches or [""]:
                found.add((m.family, touched, role))
            found.add((m.family, "hints:" + "+".join(sorted(m.hints)), role))
            for collection, key in m.atoms:
                found.add((m.family, f"atom:{collection}:{key}", role))
            found.add((m.family, "edits:" + "+".join(sorted({e.op for e in m.edits})), role))
        return frozenset(found)

    keyed = [(w, features(w)) for w in eligible]
    universe = set().union(*(f for _, f in keyed)) if keyed else set()
    cap = len(keyed) if limit is None else min(limit, len(keyed))
    # Single mutations explain a finding best, so they fill most of the budget; a quarter is kept
    # for compositions, which are most of the space.
    composed_cap = cap // 4 if limit is not None else cap
    single = [(w, f) for w, f in keyed if len(w.world.path) <= 1]
    composed = [(w, f) for w, f in keyed if len(w.world.path) > 1]
    chosen_single, seen = _greedy(single, cap - min(composed_cap, len(composed)))
    chosen_composed, seen_composed = _greedy(composed, cap - len(chosen_single))
    ever = seen | seen_composed
    ordered = _interleave(chosen_single, chosen_composed)
    totals = {
        "generated": len(worlds),
        "unjudgeable": sum(1 for w in worlds if w.role is Role.UNJUDGEABLE),
        "unobservable": sum(
            1 for w in worlds if w.role is not Role.UNJUDGEABLE and not w.observable
        ),
        "eligible": len(eligible),
        "selected": len(ordered),
        "not_selected": len(eligible) - len(ordered),
        "limit": limit,
        "features_total": len(universe),
        "features_covered": len(ever),
        "selected_by_family": _count("+".join(w.families) for w in ordered),
        "selected_by_role": _count(w.role.value for w in ordered),
    }
    return ordered, totals


def _interleave(
    singles: list[GeneratedWorld], composed: list[GeneratedWorld]
) -> list[GeneratedWorld]:
    """Priority order: three single mutations, then one composition, so a run stopped early by a
    budget has still seen both kinds."""
    out: list[GeneratedWorld] = []
    s, c = iter(singles), iter(composed)
    while len(out) < len(singles) + len(composed):
        out.extend(w for _, w in zip(range(3), s, strict=False))
        out.extend(w for _, w in zip(range(1), c, strict=False))
    return out


def _count(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))


def _greedy(
    keyed: list[tuple[GeneratedWorld, frozenset[tuple[str, str, str]]]], cap: int
) -> tuple[list[GeneratedWorld], set[tuple[str, str, str]]]:
    chosen: list[GeneratedWorld] = []
    taken: set[str] = set()
    covered: set[tuple[str, str, str]] = set()
    ever: set[tuple[str, str, str]] = set()
    cleared = False
    cap = min(cap, len(keyed))
    while len(chosen) < cap:
        best: tuple[int, int] | None = None
        pick: tuple[GeneratedWorld, frozenset[tuple[str, str, str]]] | None = None
        for index, (w, f) in enumerate(keyed):
            if w.id in taken:
                continue
            key = (-len(f - covered), index)
            if best is None or key < best:
                best, pick = key, (w, f)
        if pick is None:  # pragma: no cover - cap bounds the loop
            break
        if best is not None and best[0] == 0 and not cleared:
            covered.clear()
            cleared = True
            continue
        cleared = False
        chosen.append(pick[0])
        taken.add(pick[0].id)
        covered |= pick[1]
        ever |= pick[1]
    return chosen, ever
