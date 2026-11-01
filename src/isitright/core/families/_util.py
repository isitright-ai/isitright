"""Helpers shared by the generic families."""

from __future__ import annotations

import contextlib
import copy
import re
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from isitright.core.constraints import Pattern, Unique
from isitright.core.entities import CollectionSpec, parse_instant
from isitright.core.hints import Hint, Hints
from isitright.core.mutations import AddEntity, Edit, Mutation, RemoveEntity, SetField, SetParam
from isitright.core.spec import WorldSpec
from isitright.core.values import UnsupportedPattern, pattern_value
from isitright.core.world import Atom, Entity, State


def _next_value(existing: set[Any], value: Any) -> Any:
    """The next free value after ``value``: numbers count up, a text tail of digits counts up."""
    if isinstance(value, int) and not isinstance(value, bool):
        return max([*(v for v in existing if isinstance(v, int)), value], default=0) + 1
    if isinstance(value, float):
        return max([*(v for v in existing if isinstance(v, int | float)), value]) + 1.0
    match = re.match(r"^(.*?)(\d+)$", str(value))
    if match:
        prefix, digits = match.groups()
        number = int(digits)
        while True:
            number += 1
            candidate = f"{prefix}{number:0{len(digits)}d}"
            if candidate not in existing:
                return candidate
    text = str(value)
    if text and text[-1].isalpha():
        candidate = text
        for _ in range(26 * 26):
            stepped = _step_letters(candidate)
            if stepped is None:
                break
            candidate = stepped
            if candidate not in existing:
                return candidate
    n = 1
    while f"{text}_{n}" in existing:
        n += 1
    return f"{text}_{n}"


def _step_letters(text: str) -> str | None:
    """The next string of the same letters and case ("HBR" -> "HBS", "HBZ" -> "HCA")."""
    chars = list(text)
    i = len(chars) - 1
    while i >= 0 and chars[i].isalpha() and chars[i] in "zZ":
        chars[i] = "a" if chars[i] == "z" else "A"
        i -= 1
    if i < 0 or not chars[i].isalpha():
        return None
    chars[i] = chr(ord(chars[i]) + 1)
    return "".join(chars)


def fresh_key(state: State, collection: str, key: Any, taken: set[Any]) -> Any:
    """A key not used in the collection, readable next to the one it derives from."""
    existing = {e[state.keys[collection]] for e in state.entities(collection)} | taken
    return _next_value(existing, key)


def _uniquify(
    spec: WorldSpec, state: State, collection: CollectionSpec, entity: Entity, keep: set[str]
) -> None:
    """Give a copy fresh values in fields a Unique rule covers, so the copy stays valid."""
    for rule in spec.constraints:
        if not isinstance(rule, Unique) or rule.collection != collection.name:
            continue
        for name in rule.fields:
            if name == collection.key or name in keep or entity.get(name) is None:
                continue
            existing = {e.get(name) for e in state.entities(collection.name)}
            entity[name] = _next_value(existing, entity[name])
            regex = _pattern_of(spec, f"{collection.name}.{name}")
            if regex is not None and not re.fullmatch(regex, str(entity[name])):
                with contextlib.suppress(UnsupportedPattern):  # the spec reports it
                    entity[name] = pattern_value(regex, taken=existing)


def _pattern_of(spec: WorldSpec, path: str) -> str | None:
    for rule in spec.constraints:
        if isinstance(rule, Pattern) and rule.path == path:
            return rule.regex
    return None


def clone_cluster(
    spec: WorldSpec,
    state: State,
    atom: Atom,
    overrides: dict[str, Any] | None = None,
    taken: set[Any] | None = None,
) -> tuple[list[Edit], dict[Atom, Atom]]:
    """Copy an entity with its dependent cluster, under new keys, owned references rewired."""
    taken_by: dict[str, set[Any]] = {}
    members = spec.schema.cluster(state, atom)
    ordered = sorted(members, key=lambda a: (a != atom, a[0], str(a[1])))
    mapping: dict[Atom, Atom] = {}
    for member in ordered:
        used = taken_by.setdefault(member[0], set(taken or ()) if member == atom else set())
        new_key = fresh_key(state, member[0], member[1], used)
        used.add(new_key)
        mapping[member] = (member[0], new_key)
    edits: list[Edit] = []
    for member in ordered:
        entity = copy.deepcopy(state.get(member))
        assert entity is not None
        collection = spec.schema.collection(member[0])
        entity[collection.key] = mapping[member][1]
        _uniquify(
            spec, state, collection, entity, set(overrides or {}) if member == atom else set()
        )
        for ref in collection.references:
            target = mapping.get((ref.to, entity.get(ref.field)))
            if ref.owned and target is not None:
                entity[ref.field] = target[1]
        if member == atom:
            entity.update(copy.deepcopy(overrides or {}))
        edits.append(AddEntity(collection=member[0], entity=entity))
    return edits, mapping


def removal_edits(spec: WorldSpec, state: State, atoms: Iterable[Atom]) -> list[Edit]:
    """Remove atoms together with their dependent clusters."""
    drop: set[Atom] = set()
    for atom in atoms:
        drop |= spec.schema.cluster(state, atom)
    return [
        RemoveEntity(collection=c, key=k) for c, k in sorted(drop, key=lambda a: (a[0], str(a[1])))
    ]


def scoped_entities(
    spec: WorldSpec, state: State, hints: Hints, collection: str
) -> tuple[list[Entity], list[str]]:
    """Entities a scope hint on the collection leaves in play; all of them without a hint."""
    scopes = [h for h in hints.of("scope") if h.args["collection"] == collection]
    if not scopes:
        return list(state.entities(collection)), []
    keep: dict[Any, Entity] = {}
    key = spec.schema.collection(collection).key
    for hint in scopes:
        for entity in hints.scoped(spec.schema, state, hint):
            keep[entity[key]] = entity
    return list(keep.values()), [h.name for h in scopes]


def hints_for_field(hints: Hints, collection: str, field_name: str) -> list[Hint]:
    """Hints that name a field of the collection, whatever their kind."""
    out: list[Hint] = []
    for hint in hints:
        args = hint.args
        if (
            args.get("collection") == collection
            and (args.get("field") == field_name or field_name in args.get("fields", []))
        ) or args.get("path") == f"{collection}.{field_name}":
            out.append(hint)
    return out


def field_edit(collection: CollectionSpec, entity: Entity, name: str, value: Any) -> SetField:
    return SetField(
        collection=collection.name, key=entity[collection.key], path=[name], value=value
    )


def neighbors(kind: str, value: Any) -> list[Any]:
    """The value, and the smallest steps either side, for boundary testing."""
    if value is None or isinstance(value, bool):
        return [value]
    if kind == "int" or isinstance(value, int):
        return [int(value), int(value) - 1, int(value) + 1]
    if kind in {"float", "decimal"} or isinstance(value, float):
        number = float(value)
        step = 1 if number == int(number) else 10**-2
        return [value, round(number - step, 10), round(number + step, 10)]
    if kind in {"date", "datetime"} and isinstance(value, str):
        instant = parse_instant(value)
        return [
            value,
            (instant - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            (instant + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        ]
    if isinstance(value, str):
        return [value]
    return [value]


def neighbor_text(value: str) -> str:
    """A different value one step away: the last digit moves, or a suffix is added."""
    if value and value[-1].isdigit():
        last = int(value[-1])
        return value[:-1] + str((last + 1) % 10)
    return value + "1"


def group_of(mutations: Sequence[Mutation]) -> str:
    return "hinted" if any(m.hints for m in mutations) else "unhinted"


def set_params(name: str, value: Any) -> SetParam:
    return SetParam(name=name, value=value)
