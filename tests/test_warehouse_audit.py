"""Warehouse audits on DuckDB: the UNNEST lead example, nested validity, templates, replay."""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import (
    CheckConfig,
    SqlInputError,
    check,
    export_eval_cases,
    replay_report,
    rerun_eval_case,
)
from isitright.packs.sql.models import ColumnComparisonPolicy

# Proposed fixture: pending owner review (written by Claude, who also wrote the code under test).
BQ_DDL = "CREATE TABLE `proj.shop.items` (id INT64 NOT NULL, tags ARRAY<INT64>, name STRING)"
BQ_LEFT = "SELECT t.id, tag FROM `proj.shop.items` AS t LEFT JOIN UNNEST(t.tags) AS tag"
BQ_CROSS = "SELECT t.id, tag FROM `proj.shop.items` AS t CROSS JOIN UNNEST(t.tags) AS tag"
PRESTO_DDL = "CREATE TABLE web.items (id bigint, tags array(bigint), name varchar)"
PRESTO_LEFT = "SELECT t.id, tag FROM items AS t LEFT JOIN UNNEST(t.tags) AS u(tag) ON TRUE"
PRESTO_CROSS = "SELECT t.id, tag FROM items AS t CROSS JOIN UNNEST(t.tags) AS u(tag)"


def _sizes(report) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    state = report.findings[0].divergence["candidate_state"]
    rows = [row for table in state.values() for row in table]
    arrays = [len(v) for row in rows for v in row.values() if isinstance(v, list)]
    return len(rows), max(arrays, default=0)


@pytest.mark.parametrize(
    ("dialect", "ddl", "left", "cross"),
    [
        ("bigquery", BQ_DDL, BQ_LEFT, BQ_CROSS),
        ("presto", PRESTO_DDL, PRESTO_LEFT, PRESTO_CROSS),
        ("trino", PRESTO_DDL, PRESTO_LEFT, PRESTO_CROSS),
    ],
)
def test_unnest_lead_example_is_found_from_ddl_alone_and_minimized(
    dialect: str, ddl: str, left: str, cross: str
) -> None:
    report = check(reference_sql=left, candidate_sql=cross, dialect=dialect, ddl=ddl)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    rows, longest = _sizes(report)
    assert rows <= 2 and longest <= 2
    finding = report.findings[0]
    assert finding.fidelity.found_on == "EMULATED" and finding.fidelity.verified_on is None
    assert finding.fidelity.verification is not None
    assert finding.fidelity.verification.status == "NOT_VERIFIED"
    assert report.extensions["sql"]["target_dialect"] == dialect
    assert report.extensions["sql"]["execution_engine"] == "duckdb"


def test_bigquery_stored_arrays_never_hold_null_arrays_or_null_elements() -> None:
    report = check(reference_sql=BQ_LEFT, candidate_sql=BQ_CROSS, dialect="bigquery", ddl=BQ_DDL)
    for table in report.findings[0].divergence["candidate_state"].values():
        for row in table:
            assert row["tags"] is not None
            assert all(element is not None for element in row["tags"])


def test_presto_may_hold_null_arrays_and_the_search_uses_them() -> None:
    report = check(
        reference_sql=PRESTO_LEFT, candidate_sql=PRESTO_CROSS, dialect="presto", ddl=PRESTO_DDL
    )
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND


def test_replay_and_eval_case_export_reproduce_a_warehouse_finding() -> None:
    report = check(reference_sql=BQ_LEFT, candidate_sql=BQ_CROSS, dialect="bigquery", ddl=BQ_DDL)
    assert replay_report(report)["reproduced"] is True
    cases = export_eval_cases(report)
    assert cases[0].payload["dialect"] == "bigquery"
    assert rerun_eval_case(cases[0])["reproduced"] is True


def test_equivalent_warehouse_queries_are_not_found_within_budget() -> None:
    report = check(
        reference_sql=BQ_LEFT,
        candidate_sql=BQ_LEFT + " WHERE TRUE",
        dialect="bigquery",
        ddl=BQ_DDL,
        config=CheckConfig(max_attempts=40),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET


def test_template_values_fill_both_queries_and_are_recorded() -> None:
    report = check(
        reference_sql="SELECT id FROM t WHERE ds = '<LATEST_DS>'",
        candidate_sql="SELECT id FROM t WHERE ds = '{{ LATEST_DS }}'",
        dialect="presto",
        ddl="CREATE TABLE t (id bigint, ds varchar)",
        params={"LATEST_DS": "2020-01-01", "UNUSED": "x"},
        config=CheckConfig(max_attempts=20),
    )
    template = report.extensions["sql"]["template"]
    assert template["params"]["LATEST_DS"] == "2020-01-01"
    assert template["used"] == ["LATEST_DS"] and template["unused"] == ["UNUSED"]
    assert "<LATEST_DS>" in template["original_reference_sql"]
    assert report.inputs["reference_sql"] == "SELECT id FROM t WHERE ds = '2020-01-01'"


def test_an_unfilled_placeholder_is_an_error_naming_it() -> None:
    with pytest.raises(SqlInputError, match="UNFILLED_PLACEHOLDER: <DS>"):
        check(
            reference_sql="SELECT id FROM t WHERE ds = '<DS>'",
            candidate_sql="SELECT id FROM t",
            dialect="presto",
            ddl="CREATE TABLE t (id bigint, ds varchar)",
        )


def test_unsupported_constructs_are_rejected_naming_them() -> None:
    ddl = "CREATE TABLE `p.d.t` (id INT64, arr ARRAY<INT64>)"
    for sql, text in (
        ("SELECT ARRAY_AGG(id ORDER BY id LIMIT 2) FROM t", "LIMIT inside ARRAY_AGG"),
        ("SELECT * FROM `p.d.t_*`", "wildcard table"),
        ("SELECT _TABLE_SUFFIX FROM t", "pseudo column"),
        ("SELECT ST_GEOGPOINT(1, 2) FROM t", "geography"),
    ):
        with pytest.raises(SqlInputError, match=text):
            check(reference_sql=sql, candidate_sql="SELECT id FROM t", dialect="bigquery", ddl=ddl)


def test_contained_columns_and_vectors_follow_a_benchmark_rule() -> None:
    # The candidate returns an extra column and the rows in another order: the strict default
    # policy calls that a difference, the benchmark's rule does not.
    ddl = "CREATE TABLE t (a bigint, b bigint)"
    ref, cand = "SELECT a FROM t", "SELECT b, a FROM t ORDER BY b DESC"
    strict = check(
        reference_sql=ref,
        candidate_sql=cand,
        dialect="presto",
        ddl=ddl,
        config=CheckConfig(max_attempts=30),
    )
    assert strict.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    lenient = check(
        reference_sql=ref,
        candidate_sql=cand,
        dialect="presto",
        ddl=ddl,
        config=CheckConfig(
            max_attempts=30, column_policy=ColumnComparisonPolicy.CONTAINED, null_as_zero=True
        ),
    )
    assert lenient.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert lenient.comparison_policy["columns"] == "contained"
    assert lenient.comparison_policy["null_as_zero"] is True


def test_a_pseudo_column_is_matched_without_regard_to_case_when_the_query_defines_it() -> None:
    # the benchmark rewrite defines `_TABLE_SUFFIX`; a query may spell it `_table_suffix`
    query = (
        "SELECT COUNT(*) FROM (SELECT t.*, SUBSTR(CONCAT('ev_', t.s), 4) AS _TABLE_SUFFIX "
        "FROM d.t AS t) WHERE _table_suffix = 'x'"
    )
    report = check(
        reference_sql=query,
        candidate_sql=query,
        dialect="bigquery",
        ddl="CREATE TABLE d.t (s STRING)",
        config=CheckConfig(max_attempts=10),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    with pytest.raises(SqlInputError, match="pseudo column"):
        check(
            reference_sql="SELECT COUNT(*) FROM t WHERE _table_suffix = 'x'",
            candidate_sql="SELECT 1 FROM t",
            dialect="bigquery",
            ddl="CREATE TABLE d.t (s STRING)",
        )
