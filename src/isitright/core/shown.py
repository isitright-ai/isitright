"""One world per finding: which world a finding shows, and what it was built from.

A finding reports one world. Its diff, validity, counts, reproduction result, replay artifact and
export are all about that world, and each says so by the fingerprint of the world it was built from
(`Finding.built_from`). The report model refuses a finding whose parts name different worlds, and a
0.9 report refuses a finding that names none.

The mutations a finding names are the ones whose *surviving effects* are in the shown world. The
path that produced the world the search found is kept apart, as provenance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from isitright.core.mutations import (
    AddEntity,
    Edit,
    Mutation,
    RemoveEntity,
    SetField,
    SetParam,
    UnsetField,
    World,
)
from isitright.core.world import State

EVIDENCE_PARTS = ("validity", "world_diff", "divergence", "counts", "replay", "export")
"""The parts of a finding that describe a world. ``validity``, ``world_diff`` and ``divergence`` are
always stamped; ``counts`` when the finding has run counts, ``replay`` when it names a replay
artifact and ``export`` when it names an eval case."""


def world_json_fingerprint(data: Mapping[str, Any]) -> str:
    """The fingerprint of the world stored in an artifact (``World.to_json`` form)."""
    return World.from_json(dict(data)).fingerprint()


def check_artifact_world(
    stored: Mapping[str, Any], fingerprint: str | None, what: str, finding_id: str
) -> None:
    """Refuse an artifact whose stored world is not the world its finding shows.

    A stamp written by the code that built a finding is not proof that the artifact holds that
    world; this reads the world out of the artifact. A finding with no fingerprint (a report from
    before 0.9) is not checked.
    """
    if fingerprint is not None and world_json_fingerprint(stored) != fingerprint:
        raise ValueError(f"the world stored in the {what} is not the world of finding {finding_id}")


def built_from(fingerprint: str, *parts: str) -> dict[str, str]:
    """``{part: fingerprint}`` for the parts built from one world."""
    unknown = sorted(set(parts) - set(EVIDENCE_PARTS))
    if unknown:
        raise ValueError(f"not a part of a finding: {', '.join(unknown)}")
    return dict.fromkeys(parts, fingerprint)


# -- which mutations are still in the world ---------------------------------------------------


def surviving_path(
    path: Sequence[Mutation], shown: World, base: State | None
) -> tuple[Mutation, ...]:
    """The mutations of ``path`` with a demonstrable effect in ``shown``.

    A state mutation survives when one of its edits is still in effect: not overwritten by a later
    edit of the same target (a later mutation may set the same field), and present in ``shown``
    with the value the edit gave it (an added row is present, a removed row is absent, a set field
    holds the assigned value and differs from ``base``, an unset field is absent, a parameter holds
    its value). A response or timing mutation survives when its response edit or timer is still in
    the shown world. A mutation with no traceable edits is not claimed: nothing shows an effect.
    The result may be empty while the world still differs from ``base``; the caller then says that
    the mutation is undetermined.
    """
    if base is None:
        return tuple(path)
    edits = [(i, e) for i, m in enumerate(path) if m.target == "state" for e in m.edits]
    kept: list[Mutation] = []
    for index, mutation in enumerate(path):
        if mutation.target == "response":
            if mutation.response is not None and mutation.response in shown.response_edits:
                kept.append(mutation)
        elif mutation.target == "timing":
            if any(
                t.trigger == mutation.trigger and t.edits == mutation.edits for t in shown.timers
            ):
                kept.append(mutation)
        elif any(_survives(edit, index, edits, shown.state, base) for edit in mutation.edits):
            kept.append(mutation)
    return tuple(kept)


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


def _key_of(edit: Edit, state: State) -> Any:
    if isinstance(edit, AddEntity):
        name = state.keys.get(edit.collection)
        return edit.entity.get(name) if name is not None else None
    return edit.key  # type: ignore[union-attr]


def _covers(later: Edit, earlier: Edit, state: State) -> bool:
    """Whether ``later`` overwrites what ``earlier`` wrote."""
    if isinstance(later, SetParam):
        return isinstance(earlier, SetParam) and later.name == earlier.name
    if isinstance(earlier, SetParam) or later.collection != earlier.collection:
        return False
    if _key_of(later, state) != _key_of(earlier, state):
        return False
    if isinstance(later, AddEntity | RemoveEntity):
        return True  # a row added or removed again replaces everything written to that row
    if isinstance(earlier, SetField | UnsetField):
        return tuple(earlier.path[: len(later.path)]) == tuple(later.path)
    return False


def _survives(
    edit: Edit, index: int, edits: Sequence[tuple[int, Edit]], shown: State, base: State
) -> bool:
    """Whether an edit's effect is in the shown world and is its own.

    A later edit of the same target that is itself in effect overwrote it; a later edit that was
    undone (a row removed and present again) did not. A later edit of a *part* of what this one
    wrote changes the value without undoing the edit, so the value is then compared with the base
    only.
    """
    later = [e for i, e in edits if i > index]
    if any(_covers(e, edit, shown) and _in_effect(e, shown, base) for e in later):
        return False
    if isinstance(edit, SetField) and any(_inside(e, edit, shown) for e in later):
        row = _row(shown, edit.collection, edit.key)
        before = _value_at(_row(base, edit.collection, edit.key), edit.path)
        return row is not None and bool(_value_at(row, edit.path) != before)
    return _in_effect(edit, shown, base)


def _inside(later: Edit, earlier: SetField, state: State) -> bool:
    """Whether ``later`` writes a field strictly inside the value ``earlier`` set."""
    return (
        isinstance(later, SetField | UnsetField)
        and later.collection == earlier.collection
        and _key_of(later, state) == _key_of(earlier, state)
        and len(later.path) > len(earlier.path)
        and tuple(later.path[: len(earlier.path)]) == tuple(earlier.path)
    )


def _in_effect(edit: Edit, shown: State, base: State) -> bool:
    if isinstance(edit, SetParam):
        now = shown.params.get(edit.name, _ABSENT)
        return bool(now == edit.value and now != base.params.get(edit.name, _ABSENT))
    if isinstance(edit, AddEntity):
        name = shown.keys.get(edit.collection)
        return name is not None and _row(shown, edit.collection, edit.entity.get(name)) is not None
    if isinstance(edit, RemoveEntity):
        return _row(base, edit.collection, edit.key) is not None and (
            _row(shown, edit.collection, edit.key) is None
        )
    row = _row(shown, edit.collection, edit.key)  # SetField, UnsetField
    if row is None:
        return False
    before = _value_at(_row(base, edit.collection, edit.key), edit.path)
    now = _value_at(row, edit.path)
    if isinstance(edit, UnsetField):
        return now is _ABSENT and before is not _ABSENT
    return bool(now == edit.value and now != before)


# -- saying what a finding shows ----------------------------------------------------------------


def family_phrase(path: Sequence[Any]) -> str:
    """The distinct families of a path in order, joined with " + "; empty for an empty path."""
    return " + ".join(dict.fromkeys(m.family for m in path))


def families_of(path: Sequence[Any]) -> list[str]:
    """The distinct families of a path, in order."""
    return list(dict.fromkeys(m.family for m in path))


def change_description(diff: Mapping[str, Any]) -> str:
    """The difference of a world from its base, from `diff_states`, in words."""
    parts = [
        f"{len(diff.get(kind) or [])} {kind}"
        for kind in ("added", "removed", "changed")
        if diff.get(kind)
    ]
    return ", ".join(parts) or "no state change"


def change_phrase(kept: Sequence[Any], searched: Sequence[Any], diff: Mapping[str, Any]) -> str:
    """How a headline says what changed. ``kept`` are the mutations with a surviving effect,
    ``searched`` the ones that produced the world the search found.

    "after a boundary mutation" when some survive. When the search found the world by mutations and
    none has a demonstrable effect in the world shown, the headline gives the change that is left
    and says the mutation is undetermined, instead of naming a mutation or the baseline. With no
    mutations at all the world is the base world.
    """
    if kept:
        return f"after a {family_phrase(kept)} mutation"
    if searched:
        return (
            f"on a world that differs from the base in {change_description(diff)} "
            "(which mutation caused it is undetermined)"
        )
    return "on the baseline world"


def searched_path_record(searched: Sequence[Mutation], kept: Sequence[Mutation]) -> dict[str, Any]:
    """Provenance of a finding: the mutations that produced the world the search found, apart from
    the ones with an effect in the world shown.

    ``provenance_only`` describes ``searched_path``: that history is kept for the reader and is not
    a recipe, because the shown world may be a minimization that no replay of the path
    reconstructs (replay and export use the shown world). It says nothing about the finding's
    current evidence. ``mutation_attribution``: ``SURVIVING_EFFECTS`` (some searched mutation has a
    surviving effect in the shown world: a state edit, a response edit or a timer),
    ``UNDETERMINED`` (a searched path exists but no mutation's effect can be attributed to the
    shown world) or ``NONE`` (no mutation produced the world)."""
    return {
        "provenance_only": True,
        "searched_path": [
            {"family": m.family, "target": m.target, "description": m.description} for m in searched
        ],
        "mutation_attribution": "SURVIVING_EFFECTS"
        if kept
        else ("UNDETERMINED" if searched else "NONE"),
    }
