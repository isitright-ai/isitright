"""One world per finding: which world a finding shows, and what it was built from.

A finding reports one world. Its diff, validity, counts, reproduction result, replay artifact and
export are all about that world, and each says so by the fingerprint of the world it was built from
(`Finding.built_from`). The report model refuses a finding whose parts name different worlds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from isitright.core.mutations import (
    AddEntity,
    Edit,
    Mutation,
    RemoveEntity,
    SetParam,
    World,
)
from isitright.core.world import State

EVIDENCE_PARTS = ("validity", "world_diff", "divergence", "counts", "replay", "export")
"""The parts of a finding that describe a world. ``validity`` and ``world_diff`` are always
stamped; ``counts`` when the finding has run counts, ``replay`` when it names a replay artifact and
``export`` when it names an eval case."""


def world_json_fingerprint(data: Mapping[str, Any]) -> str:
    """The fingerprint of the world stored in an artifact (``World.to_json`` form)."""
    return World.from_json(dict(data)).fingerprint()


def built_from(fingerprint: str, *parts: str) -> dict[str, str]:
    """``{part: fingerprint}`` for the parts built from one world."""
    unknown = sorted(set(parts) - set(EVIDENCE_PARTS))
    if unknown:
        raise ValueError(f"not a part of a finding: {', '.join(unknown)}")
    return dict.fromkeys(parts, fingerprint)


def surviving_path(
    path: Sequence[Mutation], shown: State, base: State | None
) -> tuple[Mutation, ...]:
    """The mutations of ``path`` whose changes are still in ``shown``.

    ``shown`` is the state after minimization and ``base`` the state the mutations started from. A
    state mutation survives when one of its edits is still in effect: a row it added is present, a
    row it removed is absent, a field it set still differs from ``base``, a parameter it set still
    differs. A response or timing mutation travels with the world and always survives, as does a
    mutation with no edits: nothing can be traced, so it is not dropped.
    """
    if base is None:
        return tuple(path)
    return tuple(
        m
        for m in path
        if m.target != "state" or not m.edits or any(_in_effect(e, shown, base) for e in m.edits)
    )


_ABSENT = object()


def _row(state: State, collection: str, key: Any) -> dict[str, Any] | None:
    name = state.keys.get(collection)
    if name is None:
        return None
    return next((r for r in state.entities(collection) if r.get(name) == key), None)


def _value_at(row: dict[str, Any] | None, path: Sequence[Any]) -> Any:
    holder: Any = row
    for token in path:
        try:
            holder = holder[token]
        except (KeyError, IndexError, TypeError):
            return _ABSENT
    return holder


def _in_effect(edit: Edit, shown: State, base: State) -> bool:
    if isinstance(edit, SetParam):
        return bool(shown.params.get(edit.name, _ABSENT) != base.params.get(edit.name, _ABSENT))
    if isinstance(edit, AddEntity):
        name = shown.keys.get(edit.collection)
        return name is not None and _row(shown, edit.collection, edit.entity.get(name)) is not None
    if isinstance(edit, RemoveEntity):
        return _row(shown, edit.collection, edit.key) is None
    row = _row(shown, edit.collection, edit.key)  # SetField, UnsetField
    if row is None:
        return False
    before = _value_at(_row(base, edit.collection, edit.key), edit.path)
    return bool(_value_at(row, edit.path) != before)
