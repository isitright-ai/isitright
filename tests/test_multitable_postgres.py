import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from isitright import CheckConfig, SuiteCase, check_suite
from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from isitright.packs.sql.postgres_server import _postgres_server
from tests.pgcompat import check_postgres, check_postgres_suite, replay_postgres

DDL = (
    "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
    "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
)
REFERENCE = "SELECT p.id FROM parent p LEFT JOIN child c ON p.id = c.parent_id"
CANDIDATE = "SELECT p.id FROM parent p JOIN child c ON p.id = c.parent_id"
HAS_POSTGRES = all(
    importlib.util.find_spec(name) is not None for name in ("embedded_postgres", "psycopg")
)


def test_sqlite_uses_related_states_for_join_counterexample(tmp_path: Path) -> None:
    database = tmp_path / "example.sqlite"
    cases = tmp_path / "cases.jsonl"
    with sqlite3.connect(database) as connection:
        connection.executescript(DDL)
    before = hashlib.sha256(database.read_bytes()).digest()
    cases.write_text(
        json.dumps({"case_id": "join", "reference_sql": REFERENCE, "candidate_sql": CANDIDATE})
        + "\n",
        encoding="utf-8",
    )
    result = check_suite(database=database, cases=cases, config=CheckConfig(max_attempts=100))
    assert result.cases[0].divergence_status.value == "COUNTEREXAMPLE_FOUND"
    # The 0.2 "join" family is now the generic families: a parent with no child (a copy of the
    # parent row) is enough to separate LEFT JOIN from JOIN.
    assert result.cases[0].findings[0].divergence["generator"] in {"duplicate", "missing", "empty"}
    assert hashlib.sha256(database.read_bytes()).digest() == before


@pytest.mark.skipif(not HAS_POSTGRES, reason="optional PostgreSQL dependencies not installed")
def test_native_join_suite_finds_minimizes_and_replays() -> None:
    suite = check_postgres_suite(
        ddl=DDL,
        cases=[SuiteCase(case_id="join", reference_sql=REFERENCE, candidate_sql=CANDIDATE)],
    )
    report = suite.cases[0]
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert report.execution_fidelity.found_on == "NATIVE_ISOLATED"
    assert report.extensions["sql"]["native_verification"] == "NATIVE_EXECUTION"
    assert report.findings[0].mutation_path[-1].family in {"duplicate", "missing", "empty"}
    assert report.findings[0].minimization["complete"] is True
    assert replay_postgres(report)["reproduced"]
    with (
        _postgres_server() as (psycopg, uri),
        psycopg.connect(uri, autocommit=True) as connection,
    ):
        cursor = connection.execute(report.findings[0].divergence["reproducer_sql"])
        outputs = []
        while True:
            if cursor.description:
                outputs.append(cursor.fetchall())
            if not cursor.nextset():
                break
        assert len(outputs) == 2
        assert outputs[0] != outputs[1]
    rows = report.findings[0].divergence["candidate_state"]["parent"]
    rows[0]["id"] = "1; DROP TABLE parent"
    import psycopg

    with pytest.raises((ValueError, psycopg.Error)):  # the value is data: the engine refuses it
        replay_postgres(report)


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="DuckDB not installed")
def test_emulated_join_is_not_native_verified() -> None:
    report = check_postgres(
        ddl=DDL,
        reference_sql=REFERENCE,
        candidate_sql=CANDIDATE,
        engine="duckdb",
        verify_native=False,
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert report.extensions["sql"]["native_verification"] == "NATIVE_UNVERIFIED"
    assert report.execution_fidelity.found_on == "EMULATED"
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="DuckDB not installed")
def test_join_without_declared_foreign_key() -> None:
    ddl = "CREATE TABLE a (id INTEGER PRIMARY KEY); CREATE TABLE b (id INTEGER PRIMARY KEY)"
    report = check_postgres(
        ddl=ddl,
        reference_sql="SELECT a.id FROM a LEFT JOIN b ON a.id = b.id",
        candidate_sql="SELECT a.id FROM a JOIN b ON a.id = b.id",
        engine="duckdb",
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="DuckDB not installed")
def test_multitable_minimization_preserves_domain_rules_and_foreign_keys() -> None:
    constraints = {"properties": {"parent": {"minItems": 2}, "child": {"minItems": 1}}}
    report = check_postgres(
        ddl=DDL,
        reference_sql=REFERENCE,
        candidate_sql=CANDIDATE,
        engine="duckdb",
        constraints=constraints,
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert "DOMAIN_VALIDATED" in report.validity.tiers
    assert sum(report.search.rejected.values()) > 0
    assert report.findings[0].minimization["complete"] is True
    assert report.findings[0].divergence["candidate_state"]["child"]
    assert replay_postgres(report)["reproduced"]


@pytest.mark.parametrize(
    "candidate",
    [
        "SELECT id FROM parent p JOIN child c ON p.id = c.parent_id",
        "SELECT p.id FROM parent p RIGHT JOIN child c ON p.id = c.parent_id",
        "SELECT p.id FROM parent p JOIN missing m ON p.id = m.id",
        "SELECT p.id FROM parent p JOIN child c USING (id)",
        "SELECT p.id FROM parent p JOIN child c ON p.id = c.parent_id; DROP TABLE parent",
    ],
)
def test_multitable_query_validation_rejects_ambiguous_and_unsafe_sql(candidate: str) -> None:
    with pytest.raises(PostgresInputError):
        check_postgres(ddl=DDL, reference_sql=REFERENCE, candidate_sql=candidate, engine="duckdb")
