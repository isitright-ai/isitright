"""Warehouse tables rarely declare keys: what the search does about duplicates, and what the
report says when a finding rests on one."""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import CheckConfig, check
from isitright.packs.sql.errors import SqlInputError

# Proposed fixture: pending owner review (constructed schema, queries and unique declarations).
DDL = "CREATE TABLE d.t (user_id INT64, name STRING)"
GOLD = "SELECT COUNT(DISTINCT user_id) FROM t"
CAND = "SELECT COUNT(user_id) FROM t"
NO_KEY = (
    "the divergence needs equal values in t.user_id, which has no declared key or unique rule: "
    "this may be a validity gap rather than a query defect"
)


def test_a_finding_that_needs_duplicates_in_an_undeclared_column_says_so() -> None:
    report = check(reference_sql=GOLD, candidate_sql=CAND, dialect="bigquery", ddl=DDL)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert NO_KEY in report.findings[0].validity.notes
    assert report.findings[0].validity.tiers == ["STRUCTURAL"]


def test_declaring_the_column_unique_removes_the_finding() -> None:
    report = check(
        reference_sql=GOLD,
        candidate_sql=CAND,
        dialect="bigquery",
        ddl=DDL,
        constraints={"properties": {"t": {"x-unique": [["user_id"]]}}},
        config=CheckConfig(max_attempts=80),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert "declared-unique:t(user_id)" in report.checked_rules


def test_a_column_level_unique_declaration_is_the_same_rule() -> None:
    constraints = {"properties": {"t": {"items": {"properties": {"user_id": {"x-unique": True}}}}}}
    report = check(
        reference_sql=GOLD,
        candidate_sql=CAND,
        dialect="bigquery",
        ddl=DDL,
        constraints=constraints,
        config=CheckConfig(max_attempts=80),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET


def test_a_divergence_that_does_not_need_duplicates_carries_no_such_note() -> None:
    report = check(
        reference_sql="SELECT user_id FROM t WHERE user_id > 3",
        candidate_sql="SELECT user_id FROM t WHERE user_id >= 3",
        dialect="bigquery",
        ddl=DDL,
    )
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert not any("no declared key" in n for n in report.findings[0].validity.notes)


def test_unique_on_an_unknown_column_is_an_input_error() -> None:
    with pytest.raises((SqlInputError, ValueError), match="unknown column"):
        check(
            reference_sql=GOLD,
            candidate_sql=CAND,
            dialect="bigquery",
            ddl=DDL,
            constraints={"properties": {"t": {"x-unique": [["nope"]]}}},
        )


def test_a_declared_unenforced_key_is_a_key_and_is_reported_as_declared() -> None:
    report = check(
        reference_sql=GOLD,
        candidate_sql=CAND,
        dialect="bigquery",
        ddl="CREATE TABLE d.t (user_id INT64 NOT NULL, name STRING, "
        "PRIMARY KEY (user_id) NOT ENFORCED)",
        config=CheckConfig(max_attempts=80),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert "PRIMARY KEY" in report.extensions["sql"]["schema_ddl"][0].upper()
