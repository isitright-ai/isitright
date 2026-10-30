import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from isitright import CheckConfig, SuiteCase, check_suite
from tests.pgcompat import check_postgres_suite

DDL = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected INTEGER)"
CASES = [
    SuiteCase(
        case_id="boundary",
        reference_sql="SELECT id FROM item WHERE amount > 100",
        candidate_sql="SELECT id FROM item WHERE amount >= 100",
    ),
    SuiteCase(
        case_id="null",
        reference_sql="SELECT COUNT(*) FROM item",
        candidate_sql="SELECT COUNT(amount) FROM item",
    ),
    SuiteCase(
        case_id="duplicate",
        reference_sql="SELECT amount FROM item",
        candidate_sql="SELECT DISTINCT amount FROM item",
    ),
    SuiteCase(
        case_id="aggregate",
        reference_sql="SELECT SUM(amount - collected) FROM item",
        candidate_sql="SELECT SUM(amount) - SUM(collected) FROM item",
    ),
]


@pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("embedded_postgres", "psycopg")),
    reason="optional PostgreSQL dependencies not installed",
)
def test_same_mutation_families_find_differences_on_both_engines(tmp_path: Path) -> None:
    database = tmp_path / "input.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(DDL)
    before = hashlib.sha256(database.read_bytes()).digest()
    suite_file = tmp_path / "cases.jsonl"
    suite_file.write_text(
        "".join(json.dumps(case.model_dump()) + "\n" for case in CASES), encoding="utf-8"
    )
    sqlite_suite = check_suite(database=database, cases=suite_file, config=CheckConfig())
    postgres_suite = check_postgres_suite(ddl=DDL, cases=CASES)
    assert {case.case_id: case.divergence_status.value for case in sqlite_suite.cases} == {
        case.case_id: "COUNTEREXAMPLE_FOUND" for case in CASES
    }
    assert {case.case_id: case.divergence_status.value for case in postgres_suite.cases} == {
        case.case_id: "COUNTEREXAMPLE_FOUND" for case in CASES
    }
    assert all(
        case.extensions["sql"]["native_verification"] == "NATIVE_EXECUTION"
        for case in postgres_suite.cases
    )
    assert hashlib.sha256(database.read_bytes()).digest() == before
