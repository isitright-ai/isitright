# Proposed fixture: pending owner review. Written by Claude.
"""``COUNTIF`` and ``count_if`` are 0 where no input is TRUE; DuckDB's ``count_if`` is NULL.

Found in review of the Spider case ``bq284``: ``COUNTIF(REGEXP_CONTAINS(LOWER(body), ...))`` over
a group whose ``body`` is NULL is 0 in BigQuery, and the emulation gave NULL, which produced a
strict difference that BigQuery does not have.
"""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.hosts import DuckdbHost
from isitright.packs.sql.mapping import build_model
from isitright.packs.sql.postgres_ddl import Schema
from isitright.packs.sql.replaying import _state
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables, to_duckdb

DDL = "CREATE TABLE d.t (g STRING, body STRING)"
ROWS = {
    "t": [
        {"g": "a", "body": None},
        {"g": "b", "body": "education"},
        {"g": "b", "body": None},
    ]
}


def _run(dialect_name: str, sql: str) -> list[list[object]]:
    dialect = get_dialect(dialect_name)
    db = parse_warehouse_schema(DDL, dialect)
    state = _state(build_model(db, dialect.name), ROWS)
    translated = to_duckdb(resolve_tables(parse_query(sql, dialect), db), dialect, db)
    host = DuckdbHost(Schema(db), dialect)
    left, _ = host.run_pair(
        state, translated.sql, translated.sql, timeout_seconds=10, max_result_rows=50
    )
    return sorted(([cell.value for cell in row] for row in left.rows), key=repr)


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("bigquery", "SELECT g, COUNTIF(REGEXP_CONTAINS(body, r'edu')) FROM t GROUP BY g"),
        ("presto", "SELECT g, count_if(regexp_like(body, 'edu')) FROM t GROUP BY g"),
    ],
)
def test_a_group_with_no_true_input_counts_zero(dialect: str, sql: str) -> None:
    assert _run(dialect, sql) == [["a", 0], ["b", 1]]


def test_no_row_at_all_counts_zero() -> None:
    assert _run("bigquery", "SELECT COUNTIF(body = 'x') FROM t WHERE g = 'zz'") == [[0]]


def test_a_window_count_keeps_its_window() -> None:
    rows = _run(
        "bigquery",
        "SELECT g, COUNTIF(body IS NULL) OVER (PARTITION BY g) AS n FROM t",
    )
    assert rows == [["a", 1], ["b", 1], ["b", 1]]


def test_the_translation_reports_the_rewrite() -> None:
    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(DDL, dialect)
    translated = to_duckdb(
        resolve_tables(parse_query("SELECT COUNTIF(body IS NULL) FROM t", dialect), db), dialect, db
    )
    assert translated.notes["countif_zero"] == 1
    assert "COALESCE(COUNT_IF(" in translated.sql
