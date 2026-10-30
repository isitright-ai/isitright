"""Minimization: delta debugging over atoms, relative to the base world, re-validating each step.

Deterministic subjects shrink the whole world: first restrict to the collections that matter, then
ddmin the remaining atoms (dependent clusters leave together), then move changed values back toward
the base world. Live agents shrink the *mutation path* instead, since an agent only sees what it
queries (`minimize_path`). The shrinker spike (decision D2 in the 0.4 notes) found no gain from
Hypothesis's shrinker over this, so there is no optional Hypothesis pass.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from isitright.core.constraints import ValidityStatus
from isitright.core.entities import ModelError
from isitright.core.mutations import EditError, Mutation, World
from isitright.core.spec import WorldSpec
from isitright.core.world import Atom, State

Entry = TypeVar("Entry", bound=Hashable)


@dataclass(frozen=True)
class Reduction(Generic[Entry]):
    kept: list[Entry]
    attempts: int
    complete: bool


def ddmin(
    entries: Sequence[Entry], *, max_attempts: int, accepts: Callable[[list[Entry]], bool]
) -> Reduction[Entry]:
    """Remove chunks while the caller confirms the smaller list still reproduces."""
    kept = list(entries)
    attempts = 0
    granularity = 2
    exhausted = False
    while kept:
        if attempts >= max_attempts:
            exhausted = True
            break
        chunk_size = math.ceil(len(kept) / granularity)
        removed = False
        for start in range(0, len(kept), chunk_size):
            if attempts >= max_attempts:
                exhausted = True
                break
            removal = set(kept[start : start + chunk_size])
            trial = [entry for entry in kept if entry not in removal]
            attempts += 1
            if accepts(trial):
                kept = trial
                removed = True
                granularity = max(2, granularity - 1)
                break
        if exhausted:
            break
        if removed:
            continue
        if granularity >= len(kept):
            break
        granularity = min(len(kept), granularity * 2)
    return Reduction(kept, attempts, not exhausted)


@dataclass(frozen=True)
class MinimizeResult:
    world: World
    atoms_before: int
    atoms_after: int
    attempts: int
    complete: bool
    changed_atoms: int
    """Atoms of the minimized world that differ from the base world."""


def minimize_world(
    spec: WorldSpec,
    world: World,
    base: State | None,
    reproduces: Callable[[World], bool],
    *,
    referenced: Iterable[str] | None = None,
    max_attempts: int = 500,
) -> MinimizeResult:
    """Shrink a disagreeing world. ``reproduces`` must re-run both sides and re-compare.

    Every trial is re-validated with the spec before ``reproduces`` is called. ``referenced`` names
    the collections the programs read; others are removed first if the disagreement survives.
    """
    attempts = 0

    def valid_and_reproduces(state: State) -> bool:
        trial = World(state, world.response_edits, world.timers, world.path)
        if spec.validate(state).status is not ValidityStatus.VALID:
            return False
        return reproduces(trial)

    state = world.state
    names = None if referenced is None else set(referenced)
    atoms_before = (
        state.size() if names is None else sum(1 for atom in state.atoms() if atom[0] in names)
    )
    complete = True
    if names is not None:
        drop = [a for a in state.atoms() if a[0] not in names]
        if drop:
            attempts += 1
            trial = state.without(_closure(spec, state, drop))
            if valid_and_reproduces(trial):
                state = trial
    units = state.atoms()

    def accepts(kept: list[Atom]) -> bool:
        nonlocal attempts
        attempts += 1
        dropped = [a for a in units if a not in set(kept)]
        return valid_and_reproduces(state.without(_closure(spec, state, dropped)))

    reduction = ddmin(units, max_attempts=max_attempts, accepts=accepts)
    complete = reduction.complete
    dropped = [a for a in units if a not in set(reduction.kept)]
    state = state.without(_closure(spec, state, dropped))
    if base is not None:
        state, extra = _revert_toward_base(
            state, base, valid_and_reproduces, max_attempts - attempts
        )
        attempts += extra
    final = World(state, world.response_edits, world.timers, world.path)
    return MinimizeResult(
        final,
        atoms_before,
        state.size(),
        attempts + reduction.attempts,
        complete,
        _changed_atoms(state, base),
    )


def _closure(spec: WorldSpec, state: State, atoms: Iterable[Atom]) -> set[Atom]:
    out: set[Atom] = set()
    for atom in atoms:
        try:
            out |= spec.schema.cluster(state, atom)
        except ModelError:  # pragma: no cover - unknown collection, remove only the atom
            out.add(atom)
    return out


def _changed_atoms(state: State, base: State | None) -> int:
    if base is None:
        return state.size()
    return sum(
        1
        for collection, rows in state.collections.items()
        for entity in rows
        if entity not in base.entities(collection)
    )


def _revert_toward_base(
    state: State,
    base: State,
    accepts: Callable[[State], bool],
    budget: int,
) -> tuple[State, int]:
    """Put changed entities, then changed fields, back to their base values where it still holds."""
    tried = 0
    for collection in list(state.collections):
        key = state.keys[collection]
        originals = {e[key]: e for e in base.entities(collection)}
        for entity in list(state.entities(collection)):
            original = originals.get(entity[key])
            if original is None or original == entity or tried >= budget:
                continue
            for name in sorted(set(entity) | set(original)):
                if entity.get(name) == original.get(name) or tried >= budget:
                    continue
                reverted = dict(entity)
                if name in original:
                    reverted[name] = original[name]
                else:
                    reverted.pop(name, None)
                rows = [reverted if e is entity else e for e in state.entities(collection)]
                trial = state.evolve({collection: rows})
                tried += 1
                if accepts(trial):
                    state, entity = trial, reverted
    return state, tried


def minimize_path(
    base: World,
    path: Sequence[Mutation],
    reproduces: Callable[[World], bool],
) -> tuple[World, bool, int]:
    """Drop mutations that the divergence does not need (for live agents). Returns the world,
    whether the path is minimal, and the number of trials."""
    kept = list(path)
    trials = 0
    changed = True
    while changed and len(kept) > 1:
        changed = False
        for i in range(len(kept)):
            candidate = kept[:i] + kept[i + 1 :]
            try:
                world = _replay_path(base, candidate)
            except EditError:
                continue
            trials += 1
            if reproduces(world):
                kept, changed = candidate, True
                break
    return _replay_path(base, kept), True, trials


def _replay_path(base: World, path: Sequence[Mutation]) -> World:
    world = World(base.state, base.response_edits, base.timers, ())
    for mutation in path:
        world = world.apply(mutation)
    return world
