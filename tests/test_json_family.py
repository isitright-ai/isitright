"""The family that edits inside JSON values: only where a scope is declared."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from isitright.core.constraints import JsonSum, ValidityStatus, ValidityTier
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, ModelError
from isitright.core.families.json import JsonEdit
from isitright.core.hints import Hint, Hints
from isitright.core.jsonpaths import (
    concrete_paths,
    duplicate_at,
    numeric_leaves,
    parse_tokens,
    remove_at,
    set_at,
    split_hint_path,
)
from isitright.core.mutations import SetField, World
from isitright.core.spec import WorldSpec
from isitright.core.world import State

SHAPE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "qty": {"type": "integer", "minimum": 1},
            "price": {"type": "number", "minimum": 0},
            "note": {"type": "string"},
        },
    },
}
ITEMS = [{"qty": 2, "price": 5.0, "note": "x"}, {"qty": 1, "price": 3.0}]


def _schema(shape: dict[str, Any] | None) -> EntitySchema:
    return EntitySchema(
        collections=[
            CollectionSpec(
                name="orders",
                key="id",
                fields=[
                    FieldSpec(name="id"),
                    FieldSpec(name="total", type="float"),
                    FieldSpec(name="items", type="json", shape=shape),
                ],
            )
        ]
    )


def _world(shape: dict[str, Any] | None = None) -> tuple[WorldSpec, World]:
    spec = WorldSpec(id="t", schema=_schema(shape))
    state = State({"orders": ({"id": "o1", "total": 13.0, "items": ITEMS},)}, {"orders": "id"})
    return spec, World(state)


HINTS = Hints(
    [
        Hint(
            kind="json_path",
            name="price",
            args={"path": "orders.items[*].price", "same_as": ["total"]},
        )
    ]
)


def test_with_no_scope_the_family_proposes_nothing() -> None:
    spec, world = _world(shape=None)
    assert list(JsonEdit().propose(spec, world, Hints())) == []
    spec, world = _world(shape={"type": "object"})  # a shape with no numeric leaf is no scope
    assert list(JsonEdit().propose(spec, world, Hints())) == []


def test_a_declared_shape_scopes_every_numeric_leaf_it_names() -> None:
    spec, world = _world(SHAPE)
    mutations = list(JsonEdit().propose(spec, world, Hints()))
    texts = [m.description for m in mutations]
    assert all(m.hints == [] and m.family == "json_edit" for m in mutations)
    assert any(".items[0].qty set to 3" in t for t in texts)
    assert any(".items[1].price set to 4.0" in t for t in texts)
    assert not any(".note" in t for t in texts)  # a string leaf is outside the numeric scope


def test_a_hint_scopes_one_path_and_every_proposal_is_one_whole_field_edit() -> None:
    spec, world = _world(shape=None)
    mutations = list(JsonEdit().propose(spec, world, HINTS))
    assert mutations and all(m.hints == ["price"] for m in mutations)
    for mutation in mutations:
        (edit,) = mutation.edits
        assert isinstance(edit, SetField) and edit.path == ["items"] and edit.key == "o1"
        assert edit.value != ITEMS
    texts = [m.description for m in mutations]
    assert any("price set to 0.0 (zero)" in t for t in texts)
    assert any("price set to 13.0 (the value of total)" in t for t in texts)
    assert any(t.endswith(".items[0] removed") for t in texts)
    assert any(t.endswith(".items[0] duplicated") for t in texts)
    assert any(t.endswith(".items[1].price removed") for t in texts)
    assert any(t.endswith(".items[1].price set to null") for t in texts)
    assert not any("qty" in t for t in texts)  # only the declared leaf is a scope
    assert not any("set to -" in t for t in texts)  # never negative from a non-negative value
    assert ITEMS[0]["price"] == 5.0  # the original value is not touched


def test_shape_bounds_are_respected_and_a_leaf_outside_the_shape_fails_validation() -> None:
    spec, world = _world(SHAPE)
    quantities = [
        m.edits[0].value[0]["qty"]  # type: ignore[union-attr]
        for m in JsonEdit().propose(spec, world, Hints())
        if "items[0].qty set to" in m.description and "null" not in m.description
    ]
    assert sorted(quantities) == [1, 3]  # the shape's minimum is 1, so zero is never proposed
    bad = world.state.evolve({"orders": [{"id": "o1", "total": 1.0, "items": [{"qty": 0}]}]})
    verdict = spec.validate(bad)
    assert verdict.status is ValidityStatus.INVALID
    assert "minimum" in verdict.problems[0] or "less than" in verdict.problems[0]


def test_without_a_rule_over_the_content_the_world_is_structural_and_says_so() -> None:
    spec, world = _world(SHAPE)
    mutation = next(
        m for m in JsonEdit().propose(spec, world, HINTS) if "price set to 0.0" in m.description
    )
    child = world.apply(mutation)
    verdict = spec.validate_world(child.state, child.path)
    assert verdict.status is ValidityStatus.VALID
    assert ValidityTier.DOMAIN_VALIDATED not in verdict.tiers
    assert "no declared rule over its content" in verdict.notes[0]


def test_a_constraint_over_a_path_inside_json_rejects_a_world_that_breaks_it() -> None:
    schema = _schema(SHAPE)
    rule = JsonSum(collection="orders", field="items", terms=["price", "qty"], equals="total")
    spec = WorldSpec(id="t", schema=schema, constraints=[rule])
    state = State({"orders": ({"id": "o1", "total": 13.0, "items": ITEMS},)}, {"orders": "id"})
    base = World(state)
    assert spec.validate_world(base.state, base.path).tiers[-1] is ValidityTier.DOMAIN_VALIDATED
    broken = list(JsonEdit().propose(spec, base, HINTS))
    valid = [m for m in broken if spec.validate_world(base.apply(m).state).status.value == "VALID"]
    assert broken and not valid  # every one-leaf edit changes the subtotal away from the total
    covered = spec.validate_world(base.state, ())
    assert covered.status is ValidityStatus.VALID
    # with the rule in place, the tier is kept for an edit the rule covers (here: a no-op path)
    assert rule.describe() == "orders: sum(items[*].price * items[*].qty) == total"


def test_hints_that_do_not_resolve_are_errors_at_load() -> None:
    schema = _schema(SHAPE)
    bad_path = Hints([Hint(kind="json_path", args={"path": "orders.items[*].colour"})])
    with pytest.raises(ModelError, match="not in the declared shape"):
        bad_path.validate(schema)
    not_json = Hints([Hint(kind="json_path", args={"path": "orders.total"})])
    with pytest.raises(ModelError, match="not json"):
        not_json.validate(schema)
    bad_same = Hints(
        [Hint(kind="json_path", args={"path": "orders.items[*].price", "same_as": ["x"]})]
    )
    with pytest.raises(ModelError, match="no field 'x'"):
        bad_same.validate(schema)
    HINTS.validate(schema)


def test_json_path_helpers() -> None:
    assert split_hint_path("orders.items[*].price") == ("orders", "items", ["*", "price"])
    assert parse_tokens("[0].a.b[*]") == [0, "a", "b", "*"]
    for text in ("orders", "orders.[0]", ".x"):
        with pytest.raises(ModelError):
            split_hint_path(text)
    with pytest.raises(ModelError):
        parse_tokens("a..b")
    assert [(p, v) for p, v in concrete_paths(ITEMS, ["*", "qty"])] == [
        ([0, "qty"], 2),
        ([1, "qty"], 1),
    ]
    assert list(concrete_paths(ITEMS, [5, "qty"])) == []
    assert list(concrete_paths({"a": 1}, ["*"])) == []
    assert set_at(ITEMS, [0, "qty"], 9)[0]["qty"] == 9 and ITEMS[0]["qty"] == 2
    assert remove_at(ITEMS, [0, "note"])[0] == {"qty": 2, "price": 5.0}
    assert len(remove_at(ITEMS, [0])) == 1 and len(duplicate_at(ITEMS, [0])) == 3
    assert numeric_leaves(SHAPE) == [["*", "qty"], ["*", "price"]]


def test_the_family_names_nothing_of_any_scenario() -> None:
    source = (
        (Path(__file__).parents[1] / "src/isitright/core/families/json.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    for word in ("shop", "maria", "refund", "airline", "customer", "order", "price", "qty"):
        # the words appear only in prose that explains the family, never as logic
        assert f'"{word}' not in source and f"'{word}" not in source
