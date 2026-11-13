"""The row-count rule (0.9): a collection's size bounds, checked on every world and every
minimization step, and declared in a data task's constraints.yaml.

Proposed fixture: pending owner review (the tables, the rule and the minimum are written by Claude).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isitright.core.constraints import (
    RowCount,
    ValidityStatus,
    constraints_from_json,
    constraints_to_json,
)
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.minimize import minimize_world
from isitright.core.mutations import World
from isitright.core.spec import WorldSpec
from isitright.core.world import State

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="t",
            key="id",
            fields=[FieldSpec(name="id", type="int"), FieldSpec(name="x", type="int")],
        )
    ]
)


def state(rows: int) -> State:
    return State({"t": tuple({"id": i, "x": i} for i in range(rows))}, {"t": "id"})


def spec(*rules: RowCount) -> WorldSpec:
    return WorldSpec(id="w", schema=SCHEMA, constraints=list(rules))


def test_a_collection_below_the_minimum_or_above_the_maximum_is_invalid() -> None:
    rule = RowCount(collection="t", min=3, max=5)
    assert rule.describe() == "t has 3 to 5 rows"
    assert spec(rule).validate(state(3)).status is ValidityStatus.VALID
    low = spec(rule).validate(state(2))
    assert low.status is ValidityStatus.INVALID
    assert low.problems == ("t has 3 to 5 rows: t has 2 rows, fewer than 3",)
    high = spec(rule).validate(state(6))
    assert high.status is ValidityStatus.INVALID and "6 rows, more than 5" in high.problems[0]
    assert RowCount(collection="t", min=3).describe() == "t has at least 3 rows"
    assert RowCount(collection="t", max=3).describe() == "t has at most 3 rows"


def test_the_rule_round_trips_through_the_constraint_language() -> None:
    data = [{"kind": "row_count", "collection": "t", "min": 3}]
    rules = constraints_from_json(data)
    assert isinstance(rules[0], RowCount) and rules[0].min == 3
    assert constraints_to_json(rules) == [
        {"kind": "row_count", "collection": "t", "min": 3, "tier": "DOMAIN_VALIDATED"}
    ]
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        constraints_from_json([{"kind": "row_count", "collection": "t", "min": -1}])


def test_minimization_stops_at_the_declared_minimum() -> None:
    """A divergence that any non-empty table reproduces shrinks to one row without the rule, and
    to three with it: the reader never sees a world the task called degenerate."""

    def reproduces(world: World) -> bool:
        return len(list(world.state.entities("t"))) >= 1

    world = World(state(8))
    free = minimize_world(spec(), world, None, reproduces)
    bounded = minimize_world(spec(RowCount(collection="t", min=3)), world, None, reproduces)
    assert len(list(free.world.state.entities("t"))) == 1
    assert len(list(bounded.world.state.entities("t"))) == 3


def test_a_data_task_declares_it_and_keeps_its_per_answer_decimals(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    from isitright.packs.data.task import load_task

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "t.csv").write_text("x,y\n1,2\n2,4\n3,7\n", encoding="utf-8")
    (tmp_path / "gold.py").write_text("result = 1\n", encoding="utf-8")
    (tmp_path / "task.yaml").write_text(
        "id: corr\n"
        "question: 'Format: @r_value[r] @p_value[p] where r_value is rounded to two decimal "
        "places, and p_value is rounded to four decimal places.'\n"
        "files: [{file: t.csv}]\n",
        encoding="utf-8",
    )
    (tmp_path / "constraints.yaml").write_text(
        "- {kind: row_count, collection: t, min: 3}\n", encoding="utf-8"
    )
    task = load_task(tmp_path)
    assert task.constraints == [RowCount(collection="t", min=3)]
    assert task.policy.per_answer == {"pvalue": 4} and task.policy.ulps == 2
    (tmp_path / "task.yaml").write_text(
        "id: corr\nquestion: 'Format: @r_value[r] @p_value[p] where r_value is rounded to two "
        "decimal places, and p_value is rounded to four decimal places.'\n"
        "files: [{file: t.csv}]\nanswer: {abs_tol: 0.05, basis: stated by the task}\n",
        encoding="utf-8",
    )
    stated = load_task(tmp_path).policy
    assert stated.abs_tol == 0.05 and stated.per_answer == {}  # a stated tolerance covers all
