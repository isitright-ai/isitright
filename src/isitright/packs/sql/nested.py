"""Edits inside nested values: arrays, structs and maps, where the queries read them.

A pack-private mutation family (decision B4). It proposes, per entity and per nested column a
query references: an array emptied or set to NULL, an element set to NULL, removed, duplicated, or
the elements reversed, a struct field or struct set to NULL, a map entry removed or given a NULL
value. A proposal is made only where the dialect allows the result in a stored table (BigQuery
stored arrays hold neither NULL elements nor, per its documentation, a NULL array), so no attempt
is spent on a world the dialect cannot hold. Each proposal is a whole-field `SetField` edit, so
replay, minimization and the entity model are unchanged. Numeric leaves are moved by the core's
JSON family, from the `json_path` hints this module's hint helper also emits.

0.9, per-path scoping: given the paths a query reads inside each column (`nested_paths`), the family
proposes edits only on those paths (an array a query iterates, a field it reads), and the hints name
only the numeric leaves on them. A column read whole, or a path not resolved, keeps every edit.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from itertools import islice
from typing import Any

from isitright.core.entities import ModelError
from isitright.core.hints import Hint, HintKind, Hints, Provenance, register_hint_kind
from isitright.core.jsonpaths import numeric_leaves, text_of
from isitright.core.mutations import Mutation, SetField, World
from isitright.core.spec import WorldSpec
from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.nested_paths import (
    ELEMENT,
    WHOLE,
    NestedPath,
    describe,
    in_scope,
    json_steps,
)
from isitright.packs.sql.typetree import TypeNode

MAX_PER_ENTITY = 40
MAX_ELEMENTS = 2
"""Elements of an array that get their own edits; the rest are left alone to bound the search."""


def _check_nested_path(schema: Any, hint: Hint) -> None:
    """A nested column a query reads: ``collection`` and ``field`` (a json field)."""
    for name in ("collection", "field"):
        if name not in hint.args:
            raise ModelError(f"hint {hint.name!r} (nested_path) needs {name}")
    spec = schema.collection(hint.args["collection"]).field(hint.args["field"])
    if spec.type != "json":
        raise ModelError(f"{hint.args['collection']}.{hint.args['field']} is not a nested column")


register_hint_kind(HintKind("nested_path", _check_nested_path))


def nested_hints(
    references: set[tuple[str, str]],
    shapes: dict[tuple[str, str], dict[str, Any]],
    paths: dict[tuple[str, str], frozenset[NestedPath]] | None = None,
) -> list[Hint]:
    """A `nested_path` hint per referenced nested column (with the paths read inside it), and a
    `json_path` per numeric leaf on those paths."""
    out: list[Hint] = []
    for table, column in sorted(references):
        scope = (paths or {}).get((table, column), frozenset({WHOLE}))
        out.append(
            Hint(
                kind="nested_path",
                name=f"nested:{table}.{column}",
                provenance=Provenance.HARVESTED_PROGRAM,
                args={"collection": table, "field": column, "paths": describe(scope)},
            )
        )
        shape = shapes.get((table, column))
        for leaf in numeric_leaves(shape) if shape else []:
            if not in_scope(json_steps(leaf), scope):
                continue
            path = f"{table}.{column}{text_of(leaf)}"
            out.append(
                Hint(
                    kind="json_path",
                    name=f"json_path:{path}",
                    provenance=Provenance.HARVESTED_PROGRAM,
                    args={"path": path},
                )
            )
    return out


class NestedEdit:
    family = "nested_edit"
    target = "state"
    consumes = frozenset({"nested_path"})

    def __init__(
        self,
        trees: dict[tuple[str, str], TypeNode],
        rules: Dialect,
        scopes: dict[tuple[str, str], frozenset[NestedPath]] | None = None,
    ) -> None:
        self.trees = trees
        self.rules = rules
        self.scopes = scopes or {}
        """The read paths per column; a column absent here is in scope whole."""

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        for hint in hints.of("nested_path"):
            collection_name, field_name = hint.args["collection"], hint.args["field"]
            tree = self.trees.get((collection_name, field_name))
            if tree is None:
                continue
            collection = spec.schema.collection(collection_name)
            nullable = collection.field(field_name).nullable
            for entity in world.state.entities(collection_name):
                value = entity.get(field_name)
                scope = self.scopes.get((collection_name, field_name), frozenset({WHOLE}))
                edits = _edits(tree, value, self.rules, [], top_nullable=nullable, scope=scope)
                for edited, what in islice(edits, MAX_PER_ENTITY):
                    key = entity[collection.key]
                    yield Mutation(
                        family=self.family,
                        description=f"{collection_name}[{key!r}].{field_name}{what}",
                        edits=[
                            SetField(
                                collection=collection_name, key=key, path=[field_name], value=edited
                            )
                        ],
                        hints=[hint.name],
                        atoms=[(collection_name, key)],
                        touches=[f"{collection_name}.{field_name}"],
                    )


def _edits(
    node: TypeNode,
    value: Any,
    rules: Dialect,
    where: list[str | int],
    *,
    top_nullable: bool | None = None,
    scope: frozenset[NestedPath] = frozenset({WHOLE}),
) -> Iterator[tuple[Any, str]]:
    """(whole new value, description suffix) for each edit inside ``value``, outermost first,
    on the paths in ``scope`` only."""
    if value is None:
        return
    here = _steps(where)
    if not in_scope(here, scope):
        return
    label = text_of(where)
    if node.kind == "ARRAY" and node.element is not None:
        nullable = rules.null_arrays if top_nullable is None else top_nullable
        if value:
            yield [], f"{label} emptied"
        if nullable:
            yield None, f"{label} set to NULL"
        for i in range(min(len(value), MAX_ELEMENTS)):
            if rules.null_elements and value[i] is not None:
                yield _with(value, i, None), f"{label}[{i}] set to NULL"
            yield value[:i] + value[i + 1 :], f"{label}[{i}] removed"
            yield (
                [*value[: i + 1], copy.deepcopy(value[i]), *value[i + 1 :]],
                (f"{label}[{i}] duplicated"),
            )
        if len(value) > 1 and value[::-1] != value:
            yield value[::-1], f"{label} reversed"
        for i in range(min(len(value), MAX_ELEMENTS)):
            for inner, what in _edits(node.element, value[i], rules, [*where, i], scope=scope):
                yield _with(value, i, inner), what
    elif node.kind == "STRUCT":
        for name, _, not_null in node.fields:
            inner_value = value.get(name)
            if not not_null and inner_value is not None and in_scope((*here, name), scope):
                yield {**value, name: None}, f"{text_of([*where, name])} set to NULL"
        for name, inner_type, _ in node.fields:
            for inner, what in _edits(
                inner_type, value.get(name), rules, [*where, name], scope=scope
            ):
                yield {**value, name: inner}, what
    elif node.kind == "MAP" and node.value is not None:
        if value:
            yield [], f"{label} emptied"
        for i in range(min(len(value), MAX_ELEMENTS)):
            yield value[:i] + value[i + 1 :], f"{label}[{i}] removed"
            if rules.null_elements and value[i][1] is not None:
                yield _with(value, i, [value[i][0], None]), f"{label}[{i}] value set to NULL"


def _steps(where: list[str | int]) -> NestedPath:
    """A location inside a value (indexes and field names) as path steps."""
    return tuple(ELEMENT if isinstance(step, int) else step for step in where)


def _with(items: list[Any], index: int, new: Any) -> list[Any]:
    out = list(items)
    out[index] = new
    return out


# --- minimization inside nested values ------------------------------------------------------------


def nested_trees(db: Any) -> dict[tuple[str, str], TypeNode]:
    """``(table, column) -> type tree`` for every nested column of a schema."""
    return {
        (t.name, c.name): c.type_tree
        for t in db.tables
        for c in t.columns
        if c.type_tree is not None and c.type_tree.nested
    }


def count_elements(node: TypeNode, value: Any) -> int:
    """How many array elements and map entries a nested value holds, at every depth."""
    if value is None:
        return 0
    if node.kind == "ARRAY" and node.element is not None:
        return len(value) + sum(count_elements(node.element, v) for v in value)
    if node.kind == "MAP":
        return len(value)
    if node.kind == "STRUCT":
        return sum(count_elements(t, value.get(n)) for n, t, _ in node.fields)
    return 0


def _smaller(node: TypeNode, value: Any) -> Iterator[Any]:
    """Copies of ``value`` with one array element or map entry fewer, at any depth."""
    if value is None:
        return
    if node.kind == "ARRAY" and node.element is not None:
        if len(value) > 1:
            for i in range(len(value)):
                yield value[:i] + value[i + 1 :]
        for i, element in enumerate(value):
            for inner in _smaller(node.element, element):
                yield _with(value, i, inner)
    elif node.kind == "MAP" and len(value) > 1:
        for i in range(len(value)):
            yield value[:i] + value[i + 1 :]
    elif node.kind == "STRUCT":
        for name, inner_type, _ in node.fields:
            for inner in _smaller(inner_type, value.get(name)):
                yield {**value, name: inner}


def shrink_nested(
    spec: WorldSpec,
    world: World,
    trees: dict[tuple[str, str], TypeNode],
    reproduces: Callable[[World], bool],
) -> tuple[World, int, int]:
    """Remove array elements while the world stays valid and the divergence stays.

    The core minimizer shrinks rows; this pass shrinks inside them. Returns the smaller world and
    the element counts before and after. Greedy to a fixpoint, so every remaining element is needed.
    """
    from dataclasses import replace

    from isitright.core.constraints import ValidityStatus
    from isitright.core.mutations import apply_edits

    def total(w: World) -> int:
        return sum(
            count_elements(tree, entity.get(column))
            for (table, column), tree in trees.items()
            for entity in w.state.entities(table)
        )

    before = total(world)
    current = world
    changed = True
    while changed:
        changed = False
        for (table, column), tree in trees.items():
            key_name = spec.schema.collection(table).key
            for entity in list(current.state.entities(table)):
                for smaller in _smaller(tree, entity.get(column)):
                    edit = SetField(
                        collection=table, key=entity[key_name], path=[column], value=smaller
                    )
                    state = apply_edits(current.state, [edit])
                    if spec.validate(state).status is not ValidityStatus.VALID:
                        continue
                    candidate = replace(current, state=state)
                    if reproduces(candidate):
                        current, changed = candidate, True
                        break
                if changed:
                    break
            if changed:
                break
    return current, before, total(current)
