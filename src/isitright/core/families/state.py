"""Generic state families over the entity model.

Each family reads the hint kinds it declares in ``consumes``. A mutation built from a hint carries
the hint's name; one built without any hint is unhinted and runs on the budget that remains.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from datetime import timedelta
from typing import Any

from isitright.core.constraints import Aggregate, field_domain
from isitright.core.entities import CollectionSpec, parse_instant
from isitright.core.families._util import (
    clone_cluster,
    field_edit,
    hints_for_field,
    neighbor_text,
    neighbors,
    removal_edits,
    scoped_entities,
)
from isitright.core.hints import Hint, Hints, lookup_matches
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
from isitright.core.spec import WorldSpec
from isitright.core.values import edge_values
from isitright.core.world import Entity, State

MAX_UNHINTED_ENTITIES = 6


def _mutation(
    family: str, description: str, edits: Sequence[Edit], hint_names: list[str], atoms: list[Any]
) -> Mutation:
    touches = []
    for edit in edits:
        if isinstance(edit, SetField | UnsetField):
            touches.append(f"{edit.collection}.{edit.path[0]}")
        elif isinstance(edit, AddEntity):
            touches.extend(f"{edit.collection}.{n}" for n in edit.entity)
        elif isinstance(edit, RemoveEntity):
            touches.append(f"{edit.collection}.*")
    return Mutation(
        family=family,
        description=description,
        edits=list(edits),
        hints=hint_names,
        atoms=[(c, k) for c, k in atoms],
        touches=sorted(set(touches)),
    )


def _label(spec: CollectionSpec, entity: Entity) -> str:
    return f"{spec.name}[{entity[spec.key]!r}]"


def _top_first(entities: list[Entity], spec: CollectionSpec, hint: Hint) -> list[Entity]:
    """Entities ordered newest/largest first under an ordering hint."""
    name, reverse = hint.args["field"], hint.args.get("direction", "desc") == "desc"
    field_spec = spec.field(name)

    def sort_key(entity: Entity) -> Any:
        value = entity.get(name)
        if field_spec.type in {"date", "datetime"}:
            return parse_instant(value)
        return value

    return sorted((e for e in entities if e.get(name) is not None), key=sort_key, reverse=reverse)


def _set_value(
    spec: WorldSpec,
    state: State,
    collection: CollectionSpec,
    entity: Entity,
    name: str,
    value: Any,
    insert: bool,
) -> tuple[list[Edit], str]:
    """Change a field in place, or insert a copy of the entity (and its cluster) with the change."""
    label = f"{_label(collection, entity)}.{name}"
    if not insert:
        return [field_edit(collection, entity, name, value)], f"{label} set to {value!r}"
    edits, _ = clone_cluster(spec, state, (collection.name, entity[collection.key]), {name: value})
    return edits, f"a copy of {_label(collection, entity)} is added with {name} = {value!r}"


class Boundary:
    """A harvested literal and its neighbors; the enum value next to a gate.

    With ``insert=True`` the change is made on an added copy of the entity instead of the entity
    itself, so the original rows stay (the shape SQL perturbations take).
    """

    family = "boundary"
    target = "state"
    consumes = frozenset({"gate", "threshold", "literal"})

    def __init__(self, insert: bool = False) -> None:
        self.insert = insert

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("gate"):
            collection = spec.schema.collection(hint.args["collection"])
            field_spec = collection.field(hint.args["field"])
            allowed = list(hint.args["allows"])
            values = [v for v in (field_spec.enum or []) if v not in allowed] + allowed
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            for entity in entities:
                for value in values:
                    if entity.get(field_spec.name) != value:
                        edits, text = _set_value(
                            spec, state, collection, entity, field_spec.name, value, self.insert
                        )
                        gate_for = (
                            f" (gate for {hint.args['action']})" if hint.args.get("action") else ""
                        )
                        yield _mutation(
                            self.family,
                            text + gate_for,
                            edits,
                            [hint.name, *scope_names],
                            [(collection.name, entity[collection.key])],
                        )
        for hint in [*hints.of("threshold"), *hints.of("literal")]:
            if "path" not in hint.args:
                continue
            collection, field_spec = spec.schema.resolve(hint.args["path"])
            if "." in hint.args["path"].split(".", 1)[1]:
                continue  # embedded fields are not boundary targets here
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            for entity in entities:
                for value in neighbors(field_spec.type, hint.args["value"]):
                    if entity.get(field_spec.name) != value:
                        edits, text = _set_value(
                            spec, state, collection, entity, field_spec.name, value, self.insert
                        )
                        yield _mutation(
                            self.family,
                            text,
                            edits,
                            [hint.name, *scope_names],
                            [(collection.name, entity[collection.key])],
                        )
        yield from self._unhinted(spec, state, hints)

    def _unhinted(self, spec: WorldSpec, state: State, hints: Hints) -> Iterator[Mutation]:
        for collection in spec.schema.collections:
            for entity in state.entities(collection.name)[:MAX_UNHINTED_ENTITIES]:
                for nested in collection.embedded:
                    for inner_key, inner in (entity.get(nested.name) or {}).items():
                        for field_spec in nested.fields:
                            for value in field_spec.enum or []:
                                if inner.get(field_spec.name) in (None, value):
                                    continue
                                yield _mutation(
                                    self.family,
                                    f"{_label(collection, entity)}.{nested.name}[{inner_key!r}]."
                                    f"{field_spec.name} set to {value!r}",
                                    [
                                        SetField(
                                            collection=collection.name,
                                            key=entity[collection.key],
                                            path=[nested.name, inner_key, field_spec.name],
                                            value=value,
                                        )
                                    ],
                                    [],
                                    [(collection.name, entity[collection.key])],
                                )
                for field_spec in collection.fields:
                    if field_spec.enum and field_spec.name in entity:
                        if hints_for_field(hints, collection.name, field_spec.name):
                            continue
                        for value in field_spec.enum:
                            if value != entity[field_spec.name]:
                                yield _mutation(
                                    self.family,
                                    f"{_label(collection, entity)}.{field_spec.name} "
                                    f"set to {value!r}",
                                    [field_edit(collection, entity, field_spec.name, value)],
                                    [],
                                    [(collection.name, entity[collection.key])],
                                )


class EdgeValue:
    """Edge cases of a field's type (from Hypothesis) on fields the hints name.

    Boundary tests the values the task and programs mention; this tries values nobody wrote down
    (zero, negative, huge or tiny numbers; empty, padded or non-ASCII text), inside any declared
    value domain. It only touches fields that a hint names, and it runs last.
    """

    family = "edge_value"
    target = "state"
    consumes = frozenset({"column", "literal", "threshold", "gate", "ordering"})

    def __init__(self, insert: bool = False) -> None:
        self.insert = insert

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for collection in spec.schema.collections:
            for field_spec in collection.fields:
                named = hints_for_field(hints, collection.name, field_spec.name)
                if not named or field_spec.name == collection.key or field_spec.enum:
                    continue
                domain = field_domain(spec.constraints, f"{collection.name}.{field_spec.name}")
                for entity in state.entities(collection.name)[:MAX_UNHINTED_ENTITIES]:
                    current = entity.get(field_spec.name)
                    kind = _edge_kind(field_spec.type, current)
                    for value in edge_values(kind, domain):
                        if value == current:
                            continue
                        edits, text = _set_value(
                            spec, state, collection, entity, field_spec.name, value, self.insert
                        )
                        yield _mutation(
                            self.family,
                            text,
                            edits,
                            [h.name for h in named],
                            [(collection.name, entity[collection.key])],
                        )


def _edge_kind(declared: str, current: Any) -> str:
    if declared != "json":
        return declared
    if isinstance(current, bool):
        return "none"
    if isinstance(current, int):
        return "int"
    if isinstance(current, float):
        return "float"
    return "text" if isinstance(current, str) else "none"


class Missing:
    """Remove a field, or set it to null where the model allows.

    With ``insert=True`` a nullable field is nulled on an added copy of the entity.
    """

    family = "missing"
    target = "state"
    consumes = frozenset({"column", "gate", "ordering", "lookup", "threshold", "literal"})

    def __init__(self, insert: bool = False) -> None:
        self.insert = insert

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for collection in spec.schema.collections:
            for field_spec in collection.fields:
                if field_spec.name == collection.key or not (
                    field_spec.nullable or field_spec.optional
                ):
                    continue
                named = hints_for_field(hints, collection.name, field_spec.name)
                entities = list(state.entities(collection.name))
                if not named:
                    entities = entities[:MAX_UNHINTED_ENTITIES]
                for entity in entities:
                    if field_spec.name not in entity or (
                        entity[field_spec.name] is None and field_spec.nullable and not self.insert
                    ):
                        continue
                    if self.insert and field_spec.nullable:
                        edits, text = _set_value(
                            spec, state, collection, entity, field_spec.name, None, True
                        )
                    else:
                        edit: Edit = (
                            SetField(
                                collection=collection.name,
                                key=entity[collection.key],
                                path=[field_spec.name],
                                value=None,
                            )
                            if field_spec.nullable
                            else UnsetField(
                                collection=collection.name,
                                key=entity[collection.key],
                                path=[field_spec.name],
                            )
                        )
                        edits = [edit]
                        text = f"{_label(collection, entity)}.{field_spec.name} " + (
                            "set to null" if field_spec.nullable else "absent"
                        )
                    yield _mutation(
                        self.family,
                        text,
                        edits,
                        [h.name for h in named],
                        [(collection.name, entity[collection.key])],
                    )


class Duplicate:
    """Copy an entity with its dependent cluster."""

    family = "duplicate"
    target = "state"
    consumes = frozenset({"scope", "column", "lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        hinted = {h.args["collection"] for h in hints.of("scope", "ordering", "lookup")}
        for collection in spec.schema.collections:
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            if collection.name not in hinted:
                entities = entities[:MAX_UNHINTED_ENTITIES]
            for entity in entities:
                atom = (collection.name, entity[collection.key])
                edits, _ = clone_cluster(spec, state, atom)
                names = scope_names or (
                    [
                        h.name
                        for h in hints.of("ordering", "lookup")
                        if h.args["collection"] == collection.name
                    ]
                )
                yield _mutation(
                    self.family,
                    f"{_label(collection, entity)} duplicated with its {len(edits) - 1} dependents",
                    edits,
                    names,
                    [atom],
                )
                yield from self._retargeted(spec, state, hints, collection, entity, names)

    def _retargeted(
        self,
        spec: WorldSpec,
        state: State,
        hints: Hints,
        collection: CollectionSpec,
        entity: Entity,
        names: list[str],
    ) -> Iterator[Mutation]:
        """A copy attached to another entity that matches the same lookup as its parent."""
        atom = (collection.name, entity[collection.key])
        for ref in collection.references:
            if ref.owned or not ref.enforced or "." in ref.to:
                continue
            parent_spec = spec.schema.collection(ref.to)
            current = state.get((ref.to, entity.get(ref.field)))
            if current is None:
                continue
            for hint in hints.of("lookup"):
                if hint.args["collection"] != ref.to:
                    continue
                matches = lookup_matches(state, hint)
                if current not in matches:
                    continue
                for other in matches:
                    if other is current or other[parent_spec.key] == entity.get(ref.field):
                        continue
                    edits, _ = clone_cluster(spec, state, atom, {ref.field: other[parent_spec.key]})
                    yield _mutation(
                        self.family,
                        f"{_label(collection, entity)} duplicated and attached to "
                        f"{_label(parent_spec, other)}, which matches the same lookup",
                        edits,
                        [*names, hint.name],
                        [atom, (ref.to, other[parent_spec.key])],
                    )


def _vary(value: Any) -> Any:
    return neighbor_text(value) if isinstance(value, str) else value


class KeyCollision:
    """Another entity matches a lookup key fully, partially, or misses it by one step."""

    family = "key_collision"
    target = "state"
    consumes = frozenset({"lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("lookup"):
            collection = spec.schema.collection(hint.args["collection"])
            fields: list[str] = hint.args["fields"]
            for entity in lookup_matches(state, hint)[:1]:
                atom = (collection.name, entity[collection.key])
                edits, _ = clone_cluster(spec, state, atom)
                yield _mutation(
                    self.family,
                    f"another {collection.name} entity matches "
                    f"{dict(zip(fields, hint.args['value'], strict=True))} exactly",
                    [
                        e
                        for e in edits
                        if isinstance(e, AddEntity) and e.collection == collection.name
                    ][:1],
                    [hint.name],
                    [atom],
                )
                for name in fields:
                    changed = _vary(entity[name])
                    clone = [
                        e
                        for e in clone_cluster(spec, state, atom, {name: changed})[0]
                        if isinstance(e, AddEntity) and e.collection == collection.name
                    ][:1]
                    yield _mutation(
                        self.family,
                        f"another {collection.name} entity matches all lookup fields but {name} "
                        f"({changed!r})",
                        clone,
                        [hint.name],
                        [atom],
                    )
                    yield _mutation(
                        self.family,
                        f"{_label(collection, entity)}.{name} moved one step to {changed!r}: "
                        "no exact match",
                        [field_edit(collection, entity, name, changed)],
                        [hint.name],
                        [atom],
                    )


class Dangling:
    """A reference to a missing entity, or the referenced entity deleted."""

    family = "dangling"
    target = "state"
    consumes = frozenset({"scope", "lookup", "column"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for collection in spec.schema.collections:
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            if not scope_names:
                entities = entities[:MAX_UNHINTED_ENTITIES]
            for ref in collection.references:
                for entity in entities:
                    value = entity.get(ref.field)
                    if value is None:
                        continue
                    atom = (collection.name, entity[collection.key])
                    missing = f"{value}_missing" if isinstance(value, str) else -1
                    yield _mutation(
                        self.family,
                        f"{_label(collection, entity)}.{ref.field} points at a missing {ref.to}",
                        [field_edit(collection, entity, ref.field, missing)],
                        scope_names,
                        [atom],
                    )
                    head, _, embedded = ref.to.partition(".")
                    if embedded:
                        for owner in state.entities(head):
                            if value in (owner.get(embedded) or {}):
                                owner_key = owner[spec.schema.collection(head).key]
                                yield _mutation(
                                    self.family,
                                    f"{head}[{owner_key!r}].{embedded}[{value!r}] deleted while "
                                    f"{_label(collection, entity)} still uses it",
                                    [
                                        UnsetField(
                                            collection=head,
                                            key=owner_key,
                                            path=[embedded, value],
                                        )
                                    ],
                                    scope_names,
                                    [atom, (head, owner_key)],
                                )
                    elif state.get((ref.to, value)) is not None:
                        target = (ref.to, value)
                        yield _mutation(
                            self.family,
                            f"{ref.to}[{value!r}] deleted while "
                            f"{_label(collection, entity)} refers to it",
                            [RemoveEntity(collection=ref.to, key=value)],
                            scope_names,
                            [atom, target],
                        )


class Empty:
    """Remove every child of an entity in one relation (with their own dependents)."""

    family = "empty"
    target = "state"
    consumes = frozenset({"scope", "lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for child in spec.schema.collections:
            for ref in child.references:
                parent_entities, scope_names = scoped_entities(spec, state, hints, ref.to)
                if "." in ref.to:
                    continue
                if not scope_names:
                    parent_entities = parent_entities[:MAX_UNHINTED_ENTITIES]
                parent_key = spec.schema.collection(ref.to).key
                lookups = [h.name for h in hints.of("lookup") if h.args["collection"] == ref.to]
                for parent in parent_entities:
                    children = [
                        (child.name, c[child.key])
                        for c in state.entities(child.name)
                        if c.get(ref.field) == parent[parent_key]
                    ]
                    if children:
                        yield _mutation(
                            self.family,
                            f"{ref.to}[{parent[parent_key]!r}] left with no {child.name}",
                            removal_edits(spec, state, children),
                            [*scope_names, *lookups] if scope_names or lookups else [],
                            children,
                        )


class Tie:
    """Two entities with equal values on an ordering field."""

    family = "tie"
    target = "state"
    consumes = frozenset({"ordering", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("ordering"):
            collection = spec.schema.collection(hint.args["collection"])
            name = hint.args["field"]
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            ranked = _top_first(entities, collection, hint)
            if not ranked:
                continue
            top = ranked[0]
            atom = (collection.name, top[collection.key])
            edits, _ = clone_cluster(spec, state, atom)
            yield _mutation(
                self.family,
                f"{_label(collection, top)} duplicated with the same {name}",
                edits,
                [hint.name, *scope_names],
                [atom],
            )
            for runner_up in ranked[1:2]:
                yield _mutation(
                    self.family,
                    f"{_label(collection, runner_up)}.{name} set equal to "
                    f"{_label(collection, top)}",
                    [field_edit(collection, runner_up, name, top[name])],
                    [hint.name, *scope_names],
                    [atom, (collection.name, runner_up[collection.key])],
                )


class CardinalityBoundary:
    """A collection's size at a harvested count, and one more."""

    family = "cardinality_boundary"
    target = "state"
    consumes = frozenset({"threshold", "ordering", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("threshold"):
            if "count" not in hint.args:
                continue
            collection = spec.schema.collection(hint.args["collection"])
            scoped = Hint(kind="scope", name=hint.name, args=dict(hint.args))
            entities = hints.scoped(spec.schema, state, scoped)
            if not entities:
                continue
            orderings = [h for h in hints.of("ordering") if h.args["collection"] == collection.name]
            for target in (hint.args["count"], hint.args["count"] + 1):
                needed = target - len(entities)
                if needed <= 0:
                    continue
                edits: list[Edit] = []
                taken_state = state
                oldest = _oldest(entities, collection, orderings[0]) if orderings else None
                for i in range(needed):
                    source = entities[i % len(entities)]
                    atom = (collection.name, source[collection.key])
                    overrides: dict[str, Any] = {}
                    if orderings and oldest is not None:
                        name = orderings[0].args["field"]
                        overrides[name] = _earlier(collection, name, oldest, i + 1)
                    new, _ = clone_cluster(spec, taken_state, atom, overrides)
                    taken_state = _apply_adds(taken_state, new)
                    edits.extend(new)
                yield _mutation(
                    self.family,
                    f"{collection.name} reaches {target} entities in scope "
                    f"(count {hint.args['count']})",
                    edits,
                    [hint.name, *[h.name for h in orderings]],
                    [(collection.name, entities[0][collection.key])],
                )


def _apply_adds(state: State, edits: list[Edit]) -> State:
    from isitright.core.mutations import apply_edits

    return apply_edits(state, edits)


def _oldest(entities: list[Entity], spec: CollectionSpec, hint: Hint) -> Entity | None:
    ranked = _top_first(
        entities, spec, Hint(kind="ordering", args={**hint.args, "direction": "asc"})
    )
    return ranked[0] if ranked else None


def _earlier(spec: CollectionSpec, name: str, entity: Entity, steps: int) -> Any:
    value = entity[name]
    if spec.field(name).type in {"date", "datetime"}:
        return (parse_instant(value) - timedelta(days=steps)).isoformat().replace("+00:00", "Z")
    return value - steps if isinstance(value, int | float) else value


class Split:
    """Replace one child with two that preserve an aggregate constraint."""

    family = "split"
    target = "state"
    consumes = frozenset({"scope", "lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for rule in spec.constraints:
            if not isinstance(rule, Aggregate) or rule.agg != "sum":
                continue
            child = spec.schema.collection(rule.child)
            parents, scope_names = scoped_entities(spec, state, hints, rule.parent)
            parent_key = spec.schema.collection(rule.parent).key
            for parent in parents[: (None if scope_names else MAX_UNHINTED_ENTITIES)]:
                for piece in state.entities(child.name):
                    if piece.get(rule.via) != parent[parent_key]:
                        continue
                    amount = piece.get(rule.child_field)
                    if not isinstance(amount, int | float) or amount <= 0:
                        continue
                    first = (
                        round(amount / 3, 2) if amount != int(amount) or amount % 3 else amount // 3
                    )
                    first = first if first else amount / 2
                    rest = round(amount - first, 10)
                    atom = (child.name, piece[child.key])
                    for label, alternative in self._variants(spec, state, child, piece):
                        edits, _ = clone_cluster(
                            spec, state, atom, {rule.child_field: rest, **alternative}
                        )
                        yield _mutation(
                            self.family,
                            f"{_label(child, piece)} split into {first} and {rest}{label}",
                            [field_edit(child, piece, rule.child_field, first), *edits],
                            scope_names,
                            [atom, (rule.parent, parent[parent_key])],
                        )

    @staticmethod
    def _variants(
        spec: WorldSpec, state: State, child: CollectionSpec, piece: Entity
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        yield "", {}
        for ref in child.references:
            head, _, embedded = ref.to.partition(".")
            if not embedded or ref.enforced:
                continue
            for owner in state.entities(head):
                options = owner.get(embedded) or {}
                if piece.get(ref.field) in options:
                    for key in options:
                        if key != piece[ref.field]:
                            yield (
                                f" across {ref.field} {piece[ref.field]!r} and {key!r}",
                                {ref.field: key},
                            )


class Representation:
    """Make the textual order of timestamps disagree with their instant order."""

    family = "representation"
    target = "state"
    consumes = frozenset({"ordering", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("ordering"):
            collection = spec.schema.collection(hint.args["collection"])
            name = hint.args["field"]
            if collection.field(name).type not in {"date", "datetime"}:
                continue
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            ranked = _top_first(entities, collection, hint)
            if len(ranked) < 2:
                continue
            top = ranked[0]
            top_instant = parse_instant(top[name])
            for other in ranked[1:]:
                for hours in (2, 11):
                    instant = top_instant + timedelta(minutes=1)
                    local = instant - timedelta(hours=hours)
                    value = local.strftime("%Y-%m-%dT%H:%M:%S") + f"-{hours:02d}:00"
                    if str(value) >= str(top[name]):
                        continue  # the text must sort before the older-looking one
                    yield _mutation(
                        self.family,
                        f"{_label(collection, other)}.{name} becomes {value!r}: the newest instant "
                        f"with a text that sorts before {top[name]!r}",
                        [field_edit(collection, other, name, value)],
                        [hint.name, *scope_names],
                        [(collection.name, other[collection.key])],
                    )


class OutOfScopeExtreme:
    """An entity outside the task's scope becomes extreme on the ordering field."""

    family = "out_of_scope_extreme"
    target = "state"
    consumes = frozenset({"ordering", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in hints.of("ordering"):
            collection = spec.schema.collection(hint.args["collection"])
            inside, scope_names = scoped_entities(spec, state, hints, collection.name)
            if not scope_names:
                continue
            name = hint.args["field"]
            inside_keys = {e[collection.key] for e in inside}
            everyone = _top_first(list(state.entities(collection.name)), collection, hint)
            if not everyone:
                continue
            for entity in state.entities(collection.name):
                if entity[collection.key] in inside_keys:
                    continue
                extreme = _beyond(collection, name, everyone[0], hint.args.get("direction", "desc"))
                if entity.get(name) != extreme:
                    yield _mutation(
                        self.family,
                        f"{_label(collection, entity)} (outside the task's scope) becomes the "
                        f"extreme on {name}: {extreme!r}",
                        [field_edit(collection, entity, name, extreme)],
                        [hint.name, *scope_names],
                        [(collection.name, entity[collection.key])],
                    )


def _beyond(spec: CollectionSpec, name: str, top: Entity, direction: str) -> Any:
    sign = 1 if direction == "desc" else -1
    value = top[name]
    if spec.field(name).type in {"date", "datetime"}:
        return (parse_instant(value) + sign * timedelta(days=1)).isoformat().replace("+00:00", "Z")
    return value + sign


class Temporal:
    """The ordering field at the clock: now, and one step before it."""

    family = "temporal"
    target = "state"
    consumes = frozenset({"ordering"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        now = state.params.get("now")
        if now is None:
            return
        for hint in hints.of("ordering"):
            collection = spec.schema.collection(hint.args["collection"])
            name = hint.args["field"]
            if collection.field(name).type not in {"date", "datetime"}:
                continue
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            ranked = _top_first(entities, collection, hint)
            if ranked and ranked[0].get(name) != now:
                top = ranked[0]
                yield _mutation(
                    self.family,
                    f"{_label(collection, top)}.{name} set to the clock ({now})",
                    [field_edit(collection, top, name, now)],
                    [hint.name, *scope_names],
                    [(collection.name, top[collection.key])],
                )


class UnitsScale:
    """A numeric field scaled by 100 and 1000 (cents against dollars)."""

    family = "units_scale"
    target = "state"
    consumes = frozenset({"threshold", "literal"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for hint in [*hints.of("threshold"), *hints.of("literal")]:
            if "path" not in hint.args or hint.args["path"].count(".") != 1:
                continue
            collection, field_spec = spec.schema.resolve(hint.args["path"])
            if field_spec.type not in {"int", "float", "json"}:
                continue
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            for entity in entities:
                value = entity.get(field_spec.name)
                if isinstance(value, int | float) and value:
                    for factor in (100, 1000):
                        yield _mutation(
                            self.family,
                            f"{_label(collection, entity)}.{field_spec.name} scaled by {factor}",
                            [field_edit(collection, entity, field_spec.name, value * factor)],
                            [hint.name, *scope_names],
                            [(collection.name, entity[collection.key])],
                        )


class ReferenceSwap:
    """An entity in scope is attached to a different existing parent (an ownership change)."""

    family = "reference_swap"
    target = "state"
    consumes = frozenset({"scope", "lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        for collection in spec.schema.collections:
            entities, scope_names = scoped_entities(spec, state, hints, collection.name)
            if not scope_names:
                continue
            for ref in collection.references:
                if ref.owned or not ref.enforced or "." in ref.to:
                    continue
                parent = spec.schema.collection(ref.to)
                parents = state.entities(ref.to)
                for entity in entities:
                    for other in parents:
                        if other[parent.key] == entity.get(ref.field):
                            continue
                        yield _mutation(
                            self.family,
                            f"{_label(collection, entity)}.{ref.field} now points at "
                            f"{_label(parent, other)}",
                            [field_edit(collection, entity, ref.field, other[parent.key])],
                            scope_names,
                            [(collection.name, entity[collection.key])],
                        )


class ServiceParameter:
    """Set a declared service parameter to one of its interesting values."""

    family = "service_parameter"
    target = "state"
    consumes = frozenset({"threshold"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        for param in spec.params:
            for value in param.values:
                if world.state.params.get(param.name, param.default) != value:
                    yield Mutation(
                        family=self.family,
                        description=f"service parameter {param.name} set to {value!r}",
                        edits=[SetParam(name=param.name, value=copy.deepcopy(value))],
                        hints=[h.name for h in hints.of("threshold") if "count" in h.args],
                        touches=[f"params.{param.name}"],
                    )
