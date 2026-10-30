import importlib.util

import pytest

from isitright import SuiteCase
from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from tests.pgcompat import check_postgres, check_postgres_suite, replay_postgres

DDL = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER)"
NULL_FK_DDL = """
CREATE TABLE parent (id INTEGER PRIMARY KEY);
CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));
"""
NULL_FK_REFERENCE = "SELECT p.id FROM parent p WHERE p.id NOT IN (SELECT c.parent_id FROM child c)"
NULL_FK_CANDIDATE = (
    "SELECT p.id FROM parent p WHERE NOT EXISTS (SELECT 1 FROM child c WHERE c.parent_id = p.id)"
)


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="DuckDB not installed")
def test_null_foreign_key_exposes_subquery_semantics() -> None:
    report = check_postgres(
        ddl=NULL_FK_DDL,
        reference_sql=NULL_FK_REFERENCE,
        candidate_sql=NULL_FK_CANDIDATE,
        engine="duckdb",
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("embedded_postgres", "psycopg")),
    reason="PostgreSQL not installed",
)
def test_native_null_foreign_key_exposes_subquery_semantics() -> None:
    report = check_postgres(
        ddl=NULL_FK_DDL,
        reference_sql=NULL_FK_REFERENCE,
        candidate_sql=NULL_FK_CANDIDATE,
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="DuckDB not installed")
@pytest.mark.parametrize(
    "reference,candidate",
    [
        (
            "WITH q AS (SELECT id, amount FROM item) SELECT id FROM q WHERE amount > 100",
            "WITH q AS (SELECT id, amount FROM item) SELECT id FROM q WHERE amount >= 100",
        ),
        (
            "SELECT id FROM item WHERE id IN (SELECT id FROM item WHERE amount > 100)",
            "SELECT id FROM item WHERE id IN (SELECT id FROM item WHERE amount >= 100)",
        ),
        (
            "SELECT i.id FROM item i WHERE EXISTS "
            "(SELECT 1 FROM item j WHERE j.id = i.id AND j.amount > 100)",
            "SELECT i.id FROM item i WHERE EXISTS "
            "(SELECT 1 FROM item j WHERE j.id = i.id AND j.amount >= 100)",
        ),
        (
            "SELECT CASE WHEN amount > 100 THEN 1 ELSE 0 END FROM item",
            "SELECT CASE WHEN amount >= 100 THEN 1 ELSE 0 END FROM item",
        ),
        (
            "SELECT id FROM item WHERE amount > 100 UNION SELECT id FROM item WHERE id < 0",
            "SELECT id FROM item WHERE amount >= 100 UNION SELECT id FROM item WHERE id < 0",
        ),
        (
            "SELECT COUNT(*) FROM item HAVING COUNT(*) > 1",
            "SELECT COUNT(*) FROM item HAVING COUNT(*) >= 1",
        ),
        (
            "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM item WHERE amount > 100",
            "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM item WHERE amount >= 100",
        ),
        (
            "SELECT CAST(id AS TEXT) FROM item WHERE amount > 100",
            "SELECT CAST(id AS TEXT) FROM item WHERE amount >= 100",
        ),
    ],
)
def test_read_only_scoped_queries_find_boundary(reference: str, candidate: str) -> None:
    report = check_postgres(
        ddl=DDL, reference_sql=reference, candidate_sql=candidate, engine="duckdb"
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report


@pytest.mark.parametrize(
    "sql",
    [
        "WITH q AS (DELETE FROM item RETURNING id) SELECT id FROM q",
        "WITH RECURSIVE q AS (SELECT 1 UNION ALL SELECT 1 FROM q) SELECT * FROM q",
        "SELECT id FROM item WHERE EXISTS (SELECT 1 FROM missing)",
        "SELECT id FROM item WHERE EXISTS (SELECT pg_sleep(1))",
    ],
)
def test_scoped_query_validation_rejects_unsafe_queries(sql: str) -> None:
    with pytest.raises(PostgresInputError):
        check_postgres(
            ddl=DDL, reference_sql=sql, candidate_sql="SELECT id FROM item", engine="duckdb"
        )


@pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("embedded_postgres", "psycopg")),
    reason="PostgreSQL not installed",
)
def test_native_scoped_and_common_constructs() -> None:
    cases = [
        SuiteCase(
            case_id="correlated",
            reference_sql="SELECT i.id FROM item i WHERE EXISTS "
            "(SELECT 1 FROM item j WHERE j.id = i.id AND j.amount > 100)",
            candidate_sql="SELECT i.id FROM item i WHERE EXISTS "
            "(SELECT 1 FROM item j WHERE j.id = i.id AND j.amount >= 100)",
        ),
        SuiteCase(
            case_id="window",
            reference_sql="SELECT ROW_NUMBER() OVER (ORDER BY id) FROM item WHERE amount > 100",
            candidate_sql="SELECT ROW_NUMBER() OVER (ORDER BY id) FROM item WHERE amount >= 100",
        ),
        SuiteCase(
            case_id="set",
            reference_sql="SELECT id FROM item WHERE amount > 100 "
            "UNION SELECT id FROM item WHERE id < 0",
            candidate_sql="SELECT id FROM item WHERE amount >= 100 "
            "UNION SELECT id FROM item WHERE id < 0",
        ),
        SuiteCase(
            case_id="case",
            reference_sql="SELECT CASE WHEN amount > 100 THEN 1 ELSE 0 END FROM item",
            candidate_sql="SELECT CASE WHEN amount >= 100 THEN 1 ELSE 0 END FROM item",
        ),
        SuiteCase(
            case_id="having",
            reference_sql="SELECT COUNT(*) FROM item HAVING COUNT(*) > 1",
            candidate_sql="SELECT COUNT(*) FROM item HAVING COUNT(*) >= 1",
        ),
        SuiteCase(
            case_id="cast",
            reference_sql="SELECT CAST(id AS TEXT) FROM item WHERE amount > 100",
            candidate_sql="SELECT CAST(id AS TEXT) FROM item WHERE amount >= 100",
        ),
    ]
    result = check_postgres_suite(ddl=DDL, cases=cases)
    assert {item.case_id: item.divergence_status.value for item in result.cases} == {
        case.case_id: "COUNTEREXAMPLE_FOUND" for case in cases
    }
    assert replay_postgres(next(item for item in result.cases if item.case_id == "correlated"))[
        "reproduced"
    ]
