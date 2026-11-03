"""Generate a scenario's worlds with the core's families and annotate each one.

Every generated world carries its validity tiers, whether an agent could see the change at all, its
role from the reference procedure, and the mutation path with the hints behind it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from isitright.core.constraints import Validity, ValidityStatus, ValidityTier
from isitright.core.families import default_mutators
from isitright.core.families._util import neighbors
from isitright.core.hints import Hint, Provenance, lookup_matches
from isitright.core.mutations import Candidate, EditError, Mutation, SetField, World
from isitright.core.oracles import Role
from isitright.core.search import Evaluation, Progress, SearchResult, Verdict, search
from isitright.core.selection import Feature as Feature
from isitright.core.selection import coverage_order as coverage_order
from isitright.core.selection import features_of as features_of
from isitright.core.selection import greedy_cover as _greedy
from isitright.core.selection import interleave as _interleave
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
    # A proposed lookup is a guess until confirmed: it may steer the search, never a tier.
    lookups = [h for h in scenario.hints.of("lookup") if h.provenance is not Provenance.PROPOSED]
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
    problem = _cutoff_problem(scenario, world)
    reference = (
        Reference(Role.UNJUDGEABLE, problem, None, 0, problem)
        if problem is not None
        else reference_outcome(scenario, world)
    )
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


def _cutoff_problem(scenario: McpScenario, world: World) -> str | None:
    """Why a world on the exact cut-off of a threshold hint cannot be judged, or None.

    The hint must say whether the cut-off value counts as inside (``inclusive`` and ``holds``);
    without it the reference's operator decides the role, and that is a choice, not a fact about
    the policy. When the hint does say, the reference must agree: the world on the cut-off must
    have the role of the neighbor on the side the hint puts it, not the other.
    """
    thresholds = {h.name: h for h in scenario.hints.of("threshold") if "path" in h.args}
    for index, mutation in enumerate(world.path):
        for edit in mutation.edits:
            if not isinstance(edit, SetField) or len(edit.path) != 1:
                continue
            for name in mutation.hints:
                hint = thresholds.get(name)
                if hint is None:
                    continue
                collection, field = scenario.spec.schema.resolve(hint.args["path"])
                if (edit.collection, edit.path[0]) != (collection.name, field.name):
                    continue
                values = neighbors(field.type, hint.args["value"])
                if len(values) != 3 or edit.value != values[0]:
                    continue  # not an ordered value, or not exactly on the cut-off
                if "inclusive" not in hint.args:
                    return (
                        f"the world sits exactly on the cut-off of hint {name!r} "
                        f"({hint.args['value']!r}) and the hint does not say whether that value "
                        "is inside: declare inclusive and holds on the hint"
                    )
                return _cutoff_disagreement(scenario, world, index, edit, values, hint)
    return None


def _cutoff_disagreement(
    scenario: McpScenario, world: World, index: int, edit: SetField, values: list[Any], hint: Hint
) -> str | None:
    below, above = values[1], values[2]
    roles = {}
    for side, value in (("below", below), ("above", above)):
        steps = [
            m.model_copy(
                update={
                    "edits": [
                        e.model_copy(update={"value": value}) if e is edit else e for e in m.edits
                    ]
                }
            )
            if i == index
            else m
            for i, m in enumerate(world.path)
        ]
        neighbor = World(scenario.base)
        try:
            for step in steps:
                neighbor = neighbor.apply(step)
        except EditError:
            return None
        roles[side] = reference_outcome(scenario, neighbor).role
    exact = reference_outcome(scenario, world).role
    if Role.UNJUDGEABLE in {*roles.values(), exact} or roles["below"] == roles["above"]:
        return None  # nothing changes across the cut-off, or the oracle cannot say
    inside = (
        hint.args["holds"]
        if hint.args["inclusive"]
        else ("below" if hint.args["holds"] == "above" else "above")
    )
    if exact == roles[inside]:
        return None
    return (
        f"the hint {hint.name!r} declares the cut-off value "
        f"{'inside' if hint.args['inclusive'] else 'outside'} the side where its condition holds "
        f"({hint.args['holds']}), but the reference procedure treats it like the opposite side"
    )


def _world_id(path: tuple[Mutation, ...]) -> str:
    """``g<hash>_<families>``: the hash covers what the mutations change, not the order the search
    found them in or the hints behind them, so the same world has the same id under any hint arm,
    seed or attempt budget."""
    content = [
        m.model_dump(mode="json", include={"family", "target", "edits", "response", "trigger"})
        for m in path
    ]
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return f"g{digest}_" + "+".join(m.family for m in path)


def generate_worlds(
    scenario: McpScenario,
    *,
    attempts: int = 20_000,
    seed: int = 0,
    depth: int = 2,
    progress: Progress | None = None,
) -> tuple[list[GeneratedWorld], SearchResult]:
    """All valid worlds within the attempt budget (the baseline excluded), in visiting order."""
    found: list[GeneratedWorld] = []

    def collect(candidate: Candidate, validity: Validity) -> Evaluation:
        if validity.status is not ValidityStatus.VALID:  # pragma: no cover - search filters these
            return Evaluation(Verdict.REJECTED)
        path = candidate.world.path
        world_id = _world_id(path)
        taken = {w.id for w in found}
        while world_id in taken:  # two paths with the same content: keep the ids distinct
            world_id += "x"
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
        [m for m in default_mutators() if m.target == "state"]
        if scenario.external is not None
        else default_mutators(),
        collect,
        budget=Budget(attempts=attempts),
        seed=seed,
        depth=depth,
        stop_on_first=False,
        compose_from="all",
        max_parents=300,
        progress=progress,
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
    keyed = [(w, features_of(w)) for w in eligible]
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


def _count(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))
