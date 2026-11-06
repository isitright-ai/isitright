"""Nested values: the second and third constructed examples, validity per dialect, minimization
inside arrays, and comparison of nested results."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.constraints import ValidityStatus
from isitright.core.evidence import DivergenceStatus
from isitright.core.mutations import World
from isitright.core.spec import WorldSpec
from isitright.packs.sql import CheckConfig, check
from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.mapping import build_model, to_state
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    QueryResult,
    ResultColumn,
)
from isitright.packs.sql.nested import _edits, nested_trees, shrink_nested
from isitright.packs.sql.results import nested_value
from isitright.packs.sql.state import DatabaseState, TableState
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema

# Proposed fixture: pending owner review (constructed schemas and queries, written by Claude).
STRUCT_DDL = "CREATE TABLE d.t (id INT64 NOT NULL, s STRUCT<a INT64, b STRING>)"
BQ = get_dialect("bigquery")
PRESTO = get_dialect("presto")


def test_a_null_struct_field_read_by_dot_access_is_found() -> None:
    report = check(
        reference_sql="SELECT COALESCE(s.a, 0) AS v FROM t",
        candidate_sql="SELECT s.a AS v FROM t",
        dialect="bigquery",
        ddl=STRUCT_DDL,
    )
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    finding = report.findings[0]
    row = finding.divergence["candidate_state"]["t"][0]
    assert row["s"] is None or row["s"]["a"] is None


def test_null_against_empty_arrays_is_found_in_presto_and_impossible_in_bigquery() -> None:
    presto = check(
        reference_sql="SELECT id, cardinality(arr) AS n FROM t",
        candidate_sql="SELECT id, COALESCE(cardinality(arr), 0) AS n FROM t",
        dialect="presto",
        ddl="CREATE TABLE t (id bigint, arr array(bigint))",
    )
    assert presto.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert any(row["arr"] is None for row in presto.findings[0].divergence["candidate_state"]["t"])

    bigquery = check(
        reference_sql="SELECT id, ARRAY_LENGTH(arr) AS n FROM t",
        candidate_sql="SELECT id, IFNULL(ARRAY_LENGTH(arr), 0) AS n FROM t",
        dialect="bigquery",
        ddl="CREATE TABLE d.t (id INT64, arr ARRAY<INT64>)",
        config=CheckConfig(max_attempts=60),
    )
    # a stored BigQuery array is never NULL (documented), so the world that would separate the two
    # queries is not valid there; this is NOT_FOUND_WITHIN_BUDGET, not a statement of equivalence
    assert bigquery.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET


def test_proposals_respect_what_each_dialect_can_store() -> None:
    db_bq = parse_warehouse_schema("CREATE TABLE d.t (id INT64, a ARRAY<INT64>)", BQ)
    db_pr = parse_warehouse_schema("CREATE TABLE t (id bigint, a array(bigint))", PRESTO)
    tree_bq = nested_trees(db_bq)[("t", "a")]
    tree_pr = nested_trees(db_pr)[("t", "a")]
    bq = [what for _, what in _edits(tree_bq, [1, 2], BQ, [], top_nullable=False)]
    pr = [what for _, what in _edits(tree_pr, [1, 2], PRESTO, [], top_nullable=True)]
    assert any("emptied" in w for w in bq) and any("removed" in w for w in bq)
    assert not any("NULL" in w for w in bq)
    assert any("set to NULL" in w for w in pr) and any("[0] set to NULL" in w for w in pr)
    assert any("reversed" in w for w in pr)


def test_map_entries_are_never_reordered() -> None:
    db = parse_warehouse_schema("CREATE TABLE t (m map(varchar, bigint))", PRESTO)
    tree = nested_trees(db)[("t", "m")]
    whats = [w for _, w in _edits(tree, [["a", 1], ["b", 2]], PRESTO, [], top_nullable=True)]
    assert whats and not any("reversed" in w for w in whats)


def _cell(value: Any) -> CanonicalValue:
    return nested_value(value, None)


def _result(*cells: CanonicalValue) -> QueryResult:
    return QueryResult(
        columns=[ResultColumn(name=f"c{i}") for i in range(len(cells))], rows=[list(cells)]
    )


def test_nested_results_compare_arrays_in_order_structs_by_field_and_maps_without_order() -> None:
    policy = ComparisonPolicy()

    def same(a: Any, b: Any) -> bool:
        return compare_results(_result(_cell(a)), _result(_cell(b)), policy=policy).matches

    assert same([1, 2], [1, 2]) and not same([1, 2], [2, 1])
    assert same({"a": 1, "b": [1, 2]}, {"b": [1, 2], "a": 1})  # a struct or map by name, not order
    assert not same({"a": 1}, {"a": 2})
    assert same([], []) and not same([], [None])


def test_a_bigquery_result_with_a_null_array_is_an_empty_array() -> None:
    from isitright.packs.sql.postgres_server import _result as host_result

    class Cursor:
        description = [("a", "BIGINT[]")]  # noqa: RUF012

        def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
            return [(None,)]

    bigquery = host_result(Cursor(), 10, dialect=BQ)
    presto = host_result(Cursor(), 10, dialect=PRESTO)
    assert bigquery.rows[0][0].kind is CanonicalValueKind.JSON and bigquery.rows[0][0].value == []
    assert presto.rows[0][0].kind is CanonicalValueKind.NULL


def test_minimization_shrinks_arrays_to_what_the_divergence_needs() -> None:
    db = parse_warehouse_schema("CREATE TABLE d.t (id INT64 NOT NULL, a ARRAY<INT64>)", BQ)
    model = build_model(db, "bigquery")
    spec = WorldSpec(id="sql", schema=model.schema, constraints=[], python_constraints=[])
    data = DatabaseState((TableState("t", ("id", "a"), ((1, [5, 6, 7, 8]),)),))
    world = World(to_state(model, data))
    assert spec.validate(world.state).status is ValidityStatus.VALID
    # the "divergence" needs at least one element equal to 7
    needs_seven = lambda w: 7 in w.state.entities("t")[0]["a"]  # noqa: E731
    smaller, before, after = shrink_nested(spec, world, nested_trees(db), needs_seven)
    assert (before, after) == (4, 1 + 1) or after < before
    assert smaller.state.entities("t")[0]["a"] == [7]


def test_shrinking_does_not_make_a_world_invalid_for_the_dialect() -> None:
    db = parse_warehouse_schema("CREATE TABLE d.t (id INT64 NOT NULL, a ARRAY<INT64>)", BQ)
    model = build_model(db, "bigquery")
    spec = WorldSpec(id="sql", schema=model.schema, constraints=[], python_constraints=[])
    world = World(to_state(model, DatabaseState((TableState("t", ("id", "a"), ((1, [5, 6]),)),))))
    # a stored BigQuery array may be empty but never NULL; removing all elements is allowed
    smaller, _, _ = shrink_nested(spec, world, nested_trees(db), lambda w: True)
    assert smaller.state.entities("t")[0]["a"] != None  # noqa: E711
    assert spec.validate(smaller.state).status is ValidityStatus.VALID
