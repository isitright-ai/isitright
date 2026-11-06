"""Edits inside nested values: arrays, structs and maps, where the queries read them.

A pack-private mutation family (decision B4). It proposes, per entity and per nested column a
query references: an array emptied or set to NULL, an element set to NULL, removed, duplicated, or
the elements reversed, a struct field or struct set to NULL, a map entry removed or given a NULL
value. A proposal is made only where the dialect allows the result in a stored table (BigQuery
stored arrays hold neither NULL elements nor, per its documentation, a NULL array), so no attempt
is spent on a world the dialect cannot hold. Each proposal is a whole-field `SetField` edit, so
replay, minimization and the entity model are unchanged. Numeric leaves are moved by the core's
JSON family, from the `json_path` hints this module's hint helper also emits.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from itertools import islice
from typing import Any

from isitright.core.entities import ModelError
from isitright.core.hints import Hint, HintKind, Hints, Provenance, register_hint_kind
from isitright.core.jsonpaths import numeric_leaves, text_of
from isitright.core.mutations import Mutation, SetField, World
from isitright.core.spec import WorldSpec
from isitright.packs.sql.dialects import Dialect
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
    references: set[tuple[str, str]], shapes: dict[tuple[str, str], dict[str, Any]]
) -> list[Hint]:
    """A `nested_path` hint per referenced nested column, and a `json_path` per numeric leaf."""
    out: list[Hint] = []
    for table, column in sorted(references):
        out.append(
            Hint(
                kind="nested_path",
                name=f"nested:{table}.{column}",
                provenance=Provenance.HARVESTED_PROGRAM,
                args={"collection": table, "field": column},
            )
        )
        shape = shapes.get((table, column))
        for leaf in numeric_leaves(shape) if shape else []:
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

    def __init__(self, trees: dict[tuple[str, str], TypeNode], rules: Dialect) -> None:
        self.trees = trees
        self.rules = rules

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
                edits = _edits(tree, value, self.rules, [], top_nullable=nullable)
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
) -> Iterator[tuple[Any, str]]:
    """(whole new value, description suffix) for each edit inside ``value``, outermost first."""
    if value is None:
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
            for inner, what in _edits(node.element, value[i], rules, [*where, i]):
                yield _with(value, i, inner), what
    elif node.kind == "STRUCT":
        for name, _, not_null in node.fields:
            inner_value = value.get(name)
            if not not_null and inner_value is not None:
                yield {**value, name: None}, f"{text_of([*where, name])} set to NULL"
        for name, inner_type, _ in node.fields:
            for inner, what in _edits(inner_type, value.get(name), rules, [*where, name]):
                yield {**value, name: inner}, what
    elif node.kind == "MAP" and node.value is not None:
        if value:
            yield [], f"{label} emptied"
        for i in range(min(len(value), MAX_ELEMENTS)):
            yield value[:i] + value[i + 1 :], f"{label}[{i}] removed"
            if rules.null_elements and value[i][1] is not None:
                yield _with(value, i, [value[i][0], None]), f"{label}[{i}] value set to NULL"


def _with(items: list[Any], index: int, new: Any) -> list[Any]:
    out = list(items)
    out[index] = new
    return out
