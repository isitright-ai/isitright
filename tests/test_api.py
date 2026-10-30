import hashlib
import sqlite3
from pathlib import Path

import pytest

from isitright import CheckConfig, check, check_suite
from isitright.core.evidence import AttributionStatus, DivergenceStatus
from isitright.packs.sql import InputError
from isitright.packs.sql.models import ColumnComparisonPolicy


def _database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE values_table(value);
            INSERT INTO values_table VALUES (1), (2), (2);
            """
        )
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_auto_ignores_candidate_only_ordering_and_preserves_source(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    before = _sha256(database)

    result = check(
        database=database,
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT value FROM values_table ORDER BY value DESC",
    )

    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert result.validity.tiers == ["STRUCTURAL"]
    assert result.comparison_policy["effective_ordering"] == "unordered"
    assert result.original_state["outputs_match"] is True
    assert result.search.attempts > 0
    assert _sha256(database) == before


def test_check_reports_original_state_divergence(tmp_path: Path) -> None:
    result = check(
        database=_database(tmp_path / "db.sqlite"),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )

    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert result.attribution_status is AttributionStatus.UNDETERMINED
    assert result.original_state["outputs_match"] is False
    assert result.original_state["note"] == "row count differs: reference=3, candidate=2"


def test_check_reports_unsupported_sql_without_executing_it(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    before = _sha256(database)

    result = check(
        database=database,
        reference_sql="DROP TABLE values_table",
        candidate_sql="SELECT 1",
    )

    assert result.divergence_status is DivergenceStatus.UNSUPPORTED
    assert result.validity.status == "NOT_ASSESSED"
    assert result.comparison_policy["effective_ordering"] is None
    assert result.original_state["outputs_match"] is None
    assert result.errors[0]["code"] == "UNSUPPORTED_SQL"
    assert result.checked_rules == []
    assert _sha256(database) == before


def test_check_reports_execution_errors_as_inconclusive(tmp_path: Path) -> None:
    result = check(
        database=_database(tmp_path / "db.sqlite"),
        reference_sql="SELECT missing FROM values_table",
        candidate_sql="SELECT value FROM values_table",
    )

    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert result.errors[0]["code"] == "QUERY_ERROR"
    assert result.original_state["reference_result"] is None
    assert result.original_state["candidate_result"] is not None


def test_check_reports_timeout_as_inconclusive(tmp_path: Path) -> None:
    result = check(
        database=_database(tmp_path / "db.sqlite"),
        reference_sql="""
            WITH RECURSIVE forever(value) AS (
                SELECT 1 UNION ALL SELECT value + 1 FROM forever
            )
            SELECT SUM(value) FROM forever
        """,
        candidate_sql="SELECT 1",
        config=CheckConfig(timeout_seconds=0.001),
    )

    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert result.errors[0]["code"] == "QUERY_TIMEOUT"


def test_check_reports_result_resource_limit_as_inconclusive(tmp_path: Path) -> None:
    result = check(
        database=_database(tmp_path / "db.sqlite"),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT value FROM values_table",
        config=CheckConfig(max_result_rows=2),
    )

    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert [error["code"] for error in result.errors] == [
        "QUERY_RESOURCE_LIMIT",
        "QUERY_RESOURCE_LIMIT",
    ]


def test_check_reports_ambiguous_by_name_columns(tmp_path: Path) -> None:
    result = check(
        database=_database(tmp_path / "db.sqlite"),
        reference_sql="SELECT 1 AS value, 2 AS value",
        candidate_sql="SELECT 1 AS value, 2 AS value",
        config=CheckConfig(column_policy=ColumnComparisonPolicy.BY_NAME),
    )

    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert result.errors[0]["code"] == "AMBIGUOUS_COMPARISON"


def test_check_requires_a_database_file(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="database file is not readable"):
        check(
            database=tmp_path / "missing.sqlite",
            reference_sql="SELECT 1",
            candidate_sql="SELECT 1",
        )


def test_check_rejects_a_non_sqlite_file(tmp_path: Path) -> None:
    database = tmp_path / "not.sqlite"
    database.write_text("not a database", encoding="utf-8")
    with pytest.raises(InputError, match="could not open SQLite database"):
        check(database=database, reference_sql="SELECT 1", candidate_sql="SELECT 1")


def test_check_suite_requires_inputs() -> None:
    with pytest.raises(InputError, match="database file is not readable"):
        check_suite(database="db.sqlite", cases=Path("cases.jsonl"))


def test_check_requires_exactly_one_world_source() -> None:
    from isitright.packs.sql import SqlInputError

    with pytest.raises(SqlInputError, match="exactly one"):
        check(reference_sql="SELECT 1", candidate_sql="SELECT 1")
    with pytest.raises(SqlInputError, match="only supported for sqlite"):
        check(
            engine="postgres",
            database="x.sqlite",
            reference_sql="SELECT 1",
            candidate_sql="SELECT 1",
        )
