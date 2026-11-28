"""Per-path scoping of nested columns: which paths inside a nested column a query reads.

Proposed fixture: pending owner review (schemas, queries and the expected paths written by Claude,
who also wrote the resolver).
"""

from __future__ import annotations

import pytest

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.nested_paths import ALL, ELEMENT, WHOLE, describe, in_scope, nested_paths
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables

BQ = (
    "CREATE TABLE d.t (id INT64, items ARRAY<STRUCT<qty INT64, sku STRING, tags ARRAY<STRING>>>, "
    "s STRUCT<a INT64, b STRUCT<c INT64, e STRING>>, m INT64)"
)
PR = (
    "CREATE TABLE t (id BIGINT, items ARRAY(ROW(qty BIGINT, sku VARCHAR)), mp MAP(VARCHAR, BIGINT))"
)


def paths(dialect_name: str, ddl: str, *queries: str) -> dict[str, list[str]]:
    dialect = get_dialect(dialect_name)
    db = parse_warehouse_schema(ddl, dialect)
    trees = [resolve_tables(parse_query(q, dialect), db) for q in queries]
    return {f"{t}.{c}": describe(p) for (t, c), p in nested_paths(trees, db).items()}


ARRAY = "(column) (array only)"


@pytest.mark.parametrize(
    ("dialect_name", "ddl", "query", "expected"),
    [
        # an UNNEST alias, in FROM and in LEFT JOIN: the array and one field of its elements
        (
            "bigquery",
            BQ,
            "SELECT SUM(i.qty) FROM d.t, UNNEST(t.items) AS i",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        (
            "bigquery",
            BQ,
            "SELECT i.qty FROM d.t LEFT JOIN UNNEST(items) AS i",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        # dot access, qualified by the table alias or not
        ("bigquery", BQ, "SELECT s.b.c FROM d.t", {"t.s": [".b.c"]}),
        ("bigquery", BQ, "SELECT t.s.a FROM d.t AS t", {"t.s": [".a"]}),
        # a subscript is an element
        ("bigquery", BQ, "SELECT items[OFFSET(0)].sku FROM d.t", {"t.items": ["[*].sku"]}),
        # iterating an array without reading its elements
        ("bigquery", BQ, "SELECT COUNT(*) FROM d.t, UNNEST(items)", {"t.items": [ARRAY]}),
        # an array inside an array
        (
            "bigquery",
            BQ,
            "SELECT tg FROM d.t, UNNEST(items) AS i, UNNEST(i.tags) AS tg",
            {"t.items": [ARRAY, "[*].tags (array only)", "[*].tags[*]"]},
        ),
        # an element used whole
        ("bigquery", BQ, "SELECT i FROM d.t, UNNEST(items) AS i", {"t.items": [ARRAY, "[*]"]}),
        # through a CTE and a derived table, with and without an alias
        (
            "bigquery",
            BQ,
            "WITH x AS (SELECT id, items FROM d.t) SELECT i.qty FROM x, UNNEST(x.items) AS i",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        (
            "bigquery",
            BQ,
            "WITH x AS (SELECT items AS its FROM d.t) SELECT i.qty FROM x, UNNEST(its) AS i",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        ("bigquery", BQ, "SELECT z.sb.c FROM (SELECT s.b AS sb FROM d.t) AS z", {"t.s": [".b.c"]}),
        # Presto and Trino: AS u(qty, sku) names the row's fields
        (
            "presto",
            PR,
            "SELECT SUM(u.qty) FROM t CROSS JOIN UNNEST(t.items) AS u(qty, sku)",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        (
            "presto",
            PR,
            "SELECT qty FROM t CROSS JOIN UNNEST(items) AS u(qty, sku)",
            {"t.items": [ARRAY, "[*].qty"]},
        ),
        # falls back to the whole column
        ("bigquery", BQ, "SELECT ARRAY_LENGTH(items) FROM d.t", {"t.items": ["*"]}),
        ("bigquery", BQ, "SELECT * FROM d.t", {"t.items": ["*"], "t.s": ["*"]}),
        ("bigquery", BQ, "SELECT t.* FROM d.t", {"t.items": ["*"], "t.s": ["*"]}),
        ("presto", PR, "SELECT mp['a'] FROM t", {"t.mp": ["*"]}),
        ("bigquery", BQ, "SELECT s FROM d.t", {"t.s": ["*"]}),
        # a query that reads no nested column
        ("bigquery", BQ, "SELECT id, m FROM d.t", {}),
    ],
)
def test_each_reference_resolves_to_the_paths_it_reads(
    dialect_name: str, ddl: str, query: str, expected: dict[str, list[str]]
) -> None:
    assert paths(dialect_name, ddl, query) == {k: sorted(v) for k, v in expected.items()}


def test_the_paths_of_both_queries_are_united_and_a_whole_read_covers_the_rest() -> None:
    assert paths("bigquery", BQ, "SELECT s.a FROM d.t", "SELECT s.b.c FROM d.t") == {
        "t.s": [".a", ".b.c"]
    }
    assert paths("bigquery", BQ, "SELECT s.a FROM d.t", "SELECT s FROM d.t") == {"t.s": ["*"]}


def test_a_node_is_in_scope_on_the_way_to_a_read_path_or_under_a_subtree() -> None:
    read = frozenset({(ELEMENT, "qty", ALL)})
    assert in_scope((), read) and in_scope((ELEMENT,), read)
    assert in_scope((ELEMENT, "qty"), read)
    assert not in_scope((ELEMENT, "sku"), read) and not in_scope((ELEMENT, "tags", ELEMENT), read)
    assert in_scope((ELEMENT, "sku", ELEMENT), frozenset({WHOLE}))
    only_array = frozenset({()})  # COUNT(*) over UNNEST(items): the array, none of its fields
    assert in_scope((), only_array) and not in_scope((ELEMENT, "qty"), only_array)


def test_nested_edit_proposes_nothing_off_the_read_paths() -> None:
    """With every field filled, a scope that reads only ``[*].qty`` gets no edit on ``sku`` or
    ``tags``; the whole column gets edits on every field."""
    from isitright.packs.sql.nested import _edits, nested_trees

    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(BQ, dialect)
    tree = nested_trees(db)[("t", "items")]
    value = [{"qty": 1, "sku": "a", "tags": ["x"]}]
    scoped = [
        what
        for _, what in _edits(
            tree, value, dialect, [], scope=frozenset({(), (ELEMENT, "qty", ALL)})
        )
    ]
    whole = [what for _, what in _edits(tree, value, dialect, [])]
    assert scoped and all("sku" not in w and "tags" not in w for w in scoped)
    assert any(".qty" in w for w in scoped) and any("emptied" in w for w in scoped)
    assert any("sku" in w for w in whole) and any("tags" in w for w in whole)


def test_off_path_fields_are_null_in_the_base_value() -> None:
    from isitright.packs.sql.nested_paths import scoped_value

    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(BQ, dialect)
    trees = {(t.name, c.name): c.type_tree for t in db.tables for c in t.columns if c.type_tree}
    items = scoped_value(trees[("t", "items")], frozenset({(), (ELEMENT, "qty", ALL)}))
    assert items == [{"qty": 1, "sku": None, "tags": None}]
    struct = scoped_value(trees[("t", "s")], frozenset({("b", "c", ALL)}))
    assert struct == {"a": None, "b": {"c": 1, "e": None}}
    assert scoped_value(trees[("t", "s")], frozenset({WHOLE})) == {
        "a": 1,
        "b": {"c": 1, "e": "value"},
    }
