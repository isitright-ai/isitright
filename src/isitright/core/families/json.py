"""Edits inside JSON values, only where a scope is declared.

A field of type ``json`` is opaque to the other families. This one acts inside it where a hint
(``json_path``, for example ``orders.items[*].price``) or a declared shape on the field names what
is there. With neither, it proposes nothing, so it never invents nonsense such as a negative price
in an unscoped blob. Every proposal is one whole-field `SetField` edit, so replay, minimization and
the entity model are unchanged.

Within scope, per numeric leaf: moved to a neighbor, to zero, or to a value another declared field
of the entity holds (``same_as``); per list element: removed or duplicated; per key: removed or set
to null. A leaf stays inside the shape's ``minimum`` and ``maximum`` when it declares them, and a
value that is not negative never becomes negative without a declared minimum below zero.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import islice
from typing import Any

from isitright.core.families._util import scoped_entities
from isitright.core.families.state import _label, _mutation
from isitright.core.hints import Hints
from isitright.core.jsonpaths import (
    JsonPath,
    concrete_paths,
    duplicate_at,
    numeric_leaves,
    remove_at,
    set_at,
    shape_leaf,
    split_hint_path,
    text_of,
)
from isitright.core.mutations import Mutation, SetField, World
from isitright.core.spec import WorldSpec
from isitright.core.world import Entity

MAX_PER_ENTITY = 24


class JsonEdit:
    family = "json_edit"
    target = "state"
    consumes = frozenset({"json_path", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        scopes = _scopes(spec, hints)
        for (collection_name, field_name), declared in scopes.items():
            collection = spec.schema.collection(collection_name)
            entities, scope_names = scoped_entities(spec, world.state, hints, collection_name)
            for entity in entities:
                value = entity.get(field_name)
                if value is None:
                    continue
                names = [h.name for h in declared["hints"]] + scope_names
                edits = _edits(entity, value, declared)
                for edited, what in islice(edits, MAX_PER_ENTITY):
                    edit = SetField(
                        collection=collection_name,
                        key=entity[collection.key],
                        path=[field_name],
                        value=edited,
                    )
                    yield _mutation(
                        self.family,
                        f"{_label(collection, entity)}.{field_name}{what}",
                        [edit],
                        names if declared["hints"] else [],
                        [(collection_name, entity[collection.key])],
                    )


def _scopes(spec: WorldSpec, hints: Hints) -> dict[tuple[str, str], dict[str, Any]]:
    """Per json field: the leaf paths in scope and the hints that put them there."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for hint in hints.of("json_path"):
        collection, field_name, tokens = split_hint_path(str(hint.args["path"]))
        entry = out.setdefault((collection, field_name), _entry())
        entry["paths"].append((tokens, set(hint.args.get("same_as", []))))
        entry["hints"].append(hint)
    for described in spec.schema.collections:
        for field_spec in described.fields:
            if field_spec.type == "json" and field_spec.shape is not None:
                entry = out.setdefault((described.name, field_spec.name), _entry())
                entry["shape"] = field_spec.shape
                if not entry["hints"]:  # a shape alone scopes every numeric leaf it declares
                    entry["paths"].extend((p, set()) for p in numeric_leaves(field_spec.shape))
    return out


def _entry() -> dict[str, Any]:
    return {"paths": [], "hints": [], "shape": None}


def _bounds(shape: dict[str, Any] | None, tokens: JsonPath) -> tuple[Any, Any]:
    leaf = shape_leaf(shape, tokens) if shape is not None else None
    return (leaf.get("minimum"), leaf.get("maximum")) if leaf else (None, None)


def _edits(entity: Entity, value: Any, declared: dict[str, Any]) -> Iterator[tuple[Any, str]]:
    """(whole new value, description suffix) for each edit inside the declared scope."""
    seen: list[str] = []

    def fresh(edited: Any) -> bool:
        key = repr(edited)
        if edited == value or key in seen:
            return False
        seen.append(key)
        return True

    for tokens, same_as in declared["paths"]:
        low, high = _bounds(declared["shape"], tokens)
        for where, leaf in concrete_paths(value, tokens):
            label = text_of(where)
            if isinstance(leaf, int | float) and not isinstance(leaf, bool):
                for target, how in _numeric_moves(entity, leaf, same_as, low, high):
                    edited = set_at(value, where, target)
                    if fresh(edited):
                        yield edited, f"{label} set to {target!r} ({how})"
            if where:
                edited = remove_at(value, where)
                if fresh(edited):
                    yield edited, f"{label} removed"
                edited = set_at(value, where, None)
                if fresh(edited):
                    yield edited, f"{label} set to null"
            # the list element that holds this leaf: removed, or repeated
            for depth in range(len(where) - 1, -1, -1):
                if isinstance(where[depth], int):
                    element = where[: depth + 1]
                    edited = remove_at(value, element)
                    if fresh(edited):
                        yield edited, f"{text_of(element)} removed"
                    edited = duplicate_at(value, element)
                    if fresh(edited):
                        yield edited, f"{text_of(element)} duplicated"
                    break


def _numeric_moves(
    entity: Entity, leaf: float, same_as: set[str], low: Any, high: Any
) -> list[tuple[Any, str]]:
    step = 1 if isinstance(leaf, int) else 1.0
    candidates: list[tuple[Any, str]] = [
        (leaf + step, "next value up"),
        (leaf - step, "next value down"),
        (0 if isinstance(leaf, int) else 0.0, "zero"),
    ]
    for name in sorted(same_as):
        other = entity.get(name)
        if isinstance(other, int | float) and not isinstance(other, bool):
            candidates.append((other, f"the value of {name}"))
    out: list[tuple[Any, str]] = []
    for target, how in candidates:
        if target == leaf:
            continue
        if low is not None and target < low:
            continue
        if high is not None and target > high:
            continue
        if low is None and leaf >= 0 > target:
            continue
        out.append((target, how))
    return out
