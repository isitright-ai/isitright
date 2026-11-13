"""Per-path against per-column scoping on every nested fixture: no counterexample is lost.

0.9 scopes generation and the `nested_edit` family to the paths inside a nested column that the
queries read (``nested_scope="path"``, the default); ``"column"`` keeps the 0.7 behaviour (every
field of a column a query reads). On every constructed nested fixture of the test suite and the
BigQuery example, both scopes must reach the same status; where 0.7 found a counterexample, per-path
finds one too.

Proposed fixture: pending owner review (the wide-struct cases are written by Claude; the others
are the 0.7 fixtures they reuse).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import CheckConfig, check
from tests.test_warehouse_audit import (
    BQ_CROSS,
    BQ_DDL,
    BQ_LEFT,
    PRESTO_CROSS,
    PRESTO_DDL,
    PRESTO_LEFT,
)
from tests.test_warehouse_nested import STRUCT_DDL

EXAMPLE = Path(__file__).parents[1] / "examples" / "sql" / "bigquery"
WIDE_DDL = (
    "CREATE TABLE d.orders (id INT64 NOT NULL, "
    "items ARRAY<STRUCT<qty INT64, sku STRING, note STRING, price FLOAT64>>, "
    "meta STRUCT<channel STRING, region STRING, score FLOAT64>)"
)

FIXTURES: dict[str, dict[str, Any]] = {
    "unnest-bigquery": {"dialect": "bigquery", "ddl": BQ_DDL, "ref": BQ_LEFT, "cand": BQ_CROSS},
    "unnest-presto": {
        "dialect": "presto",
        "ddl": PRESTO_DDL,
        "ref": PRESTO_LEFT,
        "cand": PRESTO_CROSS,
    },
    "unnest-trino": {
        "dialect": "trino",
        "ddl": PRESTO_DDL,
        "ref": PRESTO_LEFT,
        "cand": PRESTO_CROSS,
    },
    "struct-null-field": {
        "dialect": "bigquery",
        "ddl": STRUCT_DDL,
        "ref": "SELECT COALESCE(s.a, 0) AS v FROM t",
        "cand": "SELECT s.a AS v FROM t",
    },
    "null-against-empty-presto": {
        "dialect": "presto",
        "ddl": "CREATE TABLE t (id bigint, arr array(bigint))",
        "ref": "SELECT id, cardinality(arr) AS n FROM t",
        "cand": "SELECT id, COALESCE(cardinality(arr), 0) AS n FROM t",
    },
    "array-length-bigquery": {
        "dialect": "bigquery",
        "ddl": "CREATE TABLE d.t (id INT64, arr ARRAY<INT64>)",
        "ref": "SELECT id, ARRAY_LENGTH(arr) AS n FROM t",
        "cand": "SELECT id, IFNULL(ARRAY_LENGTH(arr), 0) AS n FROM t",
        "attempts": 60,
    },
    "bigquery-example": {
        "dialect": "bigquery",
        "ddl": (EXAMPLE / "schema.sql").read_text(encoding="utf-8"),
        "ref": (EXAMPLE / "reference.sql").read_text(encoding="utf-8"),
        "cand": (EXAMPLE / "candidate.sql").read_text(encoding="utf-8"),
    },
    "wide-array-of-structs": {
        "dialect": "bigquery",
        "ddl": WIDE_DDL,
        "ref": "SELECT o.id, SUM(i.qty) AS n FROM d.orders AS o LEFT JOIN UNNEST(o.items) AS i "
        "GROUP BY o.id",
        "cand": "SELECT o.id, SUM(i.qty) AS n FROM d.orders AS o, UNNEST(o.items) AS i "
        "GROUP BY o.id",
    },
    "wide-struct-field": {
        "dialect": "bigquery",
        "ddl": WIDE_DDL,
        "ref": "SELECT id, COALESCE(meta.channel, 'web') AS c FROM d.orders",
        "cand": "SELECT id, meta.channel AS c FROM d.orders",
    },
    "wide-element-field-null": {
        "dialect": "bigquery",
        "ddl": WIDE_DDL,
        "ref": "SELECT o.id, SUM(COALESCE(i.qty, 0)) AS n FROM d.orders AS o, UNNEST(o.items) AS i "
        "GROUP BY o.id",
        "cand": "SELECT o.id, COUNT(i.qty) AS n FROM d.orders AS o, UNNEST(o.items) AS i "
        "GROUP BY o.id",
    },
}


def audit(fixture: dict[str, Any], scope: str) -> Any:
    return check(
        reference_sql=fixture["ref"],
        candidate_sql=fixture["cand"],
        dialect=fixture["dialect"],
        ddl=fixture["ddl"],
        config=CheckConfig(max_attempts=fixture.get("attempts", 500), nested_scope=scope),
    )


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_per_path_finds_what_per_column_finds(name: str) -> None:
    fixture = FIXTURES[name]
    column, path = audit(fixture, "column"), audit(fixture, "path")
    assert path.divergence_status is column.divergence_status, (name, path.headline)
    if column.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND:
        assert path.findings and path.findings[0].replay is not None
    assert column.extensions["sql"]["nested_scope"]["mode"] == "column"
    assert path.extensions["sql"]["nested_scope"]["mode"] == "path"
    # The attempts to the first finding are not compared: the two scopes propose in a different
    # order (wide-array-of-structs: 8 per path, 4 per column on 2026-11-13). When nothing is found
    # the search is exhaustive and per-path tries no more (the test below).
    assert path.search is not None and column.search is not None
    if column.divergence_status is not DivergenceStatus.COUNTEREXAMPLE_FOUND:
        assert path.search.attempts <= column.search.attempts


def _fields(state: dict[str, list[dict[str, Any]]], column: str) -> list[dict[str, Any]]:
    values = [row[column] for row in state["orders"] if row.get(column)]
    out: list[dict[str, Any]] = []
    for value in values:
        out.extend(value if isinstance(value, list) else [value])
    return out


def test_fields_no_query_reads_stay_null_per_path_and_are_filled_per_column() -> None:
    fixture = FIXTURES["wide-element-field-null"]
    path = audit(fixture, "path")
    assert path.extensions["sql"]["nested_scope"]["paths"]["orders.items"] == [
        "(column) (array only)",
        "[*].qty",
    ]
    assert "orders.meta" not in path.extensions["sql"]["nested_scope"]["paths"]  # not read
    finding = path.findings[0]
    elements = _fields(finding.divergence["candidate_state"], "items")
    assert elements and all(
        e["sku"] is None and e["note"] is None and e["price"] is None for e in elements
    )
    assert all(
        "sku" not in m.description and "note" not in m.description for m in finding.mutation_path
    )
    column = audit(fixture, "column")
    column_elements = _fields(column.findings[0].divergence["candidate_state"], "items")
    assert any(e["sku"] is not None for e in column_elements)  # 0.7 filled every field


def test_per_path_spends_fewer_attempts_on_a_wide_struct_than_per_column() -> None:
    """A query that reads one field of a wide struct: per-column proposes an edit for each field,
    per-path only for the one read."""
    fixture = {**FIXTURES["wide-struct-field"], "cand": FIXTURES["wide-struct-field"]["ref"]}
    column, path = audit(fixture, "column"), audit(fixture, "path")
    assert column.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert path.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert path.search is not None and column.search is not None
    assert path.search.attempts < column.search.attempts


def test_the_cli_takes_the_scope(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from isitright.cli import app

    fixture = FIXTURES["wide-struct-field"]
    files = {}
    for name, text in (
        ("schema", fixture["ddl"]),
        ("ref", fixture["ref"]),
        ("cand", fixture["cand"]),
    ):
        files[name] = tmp_path / f"{name}.sql"
        files[name].write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "sql",
            "check",
            "--dialect",
            "bigquery",
            "--schema",
            str(files["schema"]),
            "--reference",
            str(files["ref"]),
            "--candidate",
            str(files["cand"]),
            "--nested-scope",
            "column",
            "--output-dir",
            str(out),
        ],
    )
    assert result.exit_code in (0, 1), result.output
    import json

    report = json.loads((out / "case_report.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["extensions"]["sql"]["nested_scope"]["mode"] == "column"
