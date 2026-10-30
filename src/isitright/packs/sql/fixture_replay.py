"""Offline replay of a SQLite counterexample from its hand-readable SQL fixture.

`counterexample.sql` holds the minimized schema and rows. Replay runs it in a fresh in-memory
database under an authorizer that denies external and executable effects (ATTACH, triggers,
extension loading, unlisted PRAGMAs), then runs both queries from the report and checks that the
recorded outputs and the disagreement recur. The JSON artifact (`replay.json`) is the primary
replay input; this path exists so a reader can inspect and edit the fixture.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from isitright.core.evidence import AuditReport
from isitright.packs.sql.analysis import validate_read_only_query
from isitright.packs.sql.models import QueryResult, ResultColumn
from isitright.packs.sql.replay_comparison import reproduces_disagreement
from isitright.packs.sql.sqlite_sandbox import (
    QueryResourceLimitError,
    QueryTimeoutError,
    _read_only_authorizer,
    canonicalize_sqlite_value,
)

_REPLAY_TIMEOUT_SECONDS = 30.0
_REPLAY_MAX_RESULT_ROWS = 10_000


def replay_fixture(report_path: str | Path, fixture_path: str | Path) -> dict[str, Any]:
    """Rebuild a fixture, execute both queries, and verify the recorded outputs."""
    audit = AuditReport.model_validate_json(Path(report_path).read_text(encoding="utf-8"))
    case = audit.cases[0]
    if not case.findings:
        raise ValueError("case report does not contain counterexample evidence")
    divergence = case.findings[0].divergence
    reference_sql, candidate_sql = case.inputs["reference_sql"], case.inputs["candidate_sql"]
    validate_read_only_query(reference_sql)
    validate_read_only_query(candidate_sql)
    with sqlite3.connect(":memory:") as connection:
        connection.set_authorizer(_replay_fixture_authorizer)
        execute_fixture(connection, Path(fixture_path).read_text(encoding="utf-8"))
        connection.set_authorizer(_read_only_authorizer)
        reference = _execute(connection, reference_sql)
        candidate = _execute(connection, candidate_sql)
    reproduced = reproduces_disagreement(
        reference,
        candidate,
        QueryResult.model_validate(divergence["reference_result"]),
        QueryResult.model_validate(divergence["candidate_result"]),
        matches=lambda actual, expected: actual == expected,
    )
    return {
        "reproduced": reproduced,
        "reference_result": reference.model_dump(mode="json"),
        "candidate_result": candidate.model_dump(mode="json"),
    }


def execute_fixture(connection: sqlite3.Connection, sql: str) -> None:
    """Run a fixture script under a deadline; the caller installs the authorizer."""
    deadline = time.monotonic() + _REPLAY_TIMEOUT_SECONDS
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
    try:
        connection.executescript(sql)
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error).lower():
            raise QueryTimeoutError(
                f"replay fixture exceeded the {_REPLAY_TIMEOUT_SECONDS:g}-second budget"
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _execute(connection: sqlite3.Connection, sql: str) -> QueryResult:
    deadline = time.monotonic() + _REPLAY_TIMEOUT_SECONDS
    timed_out = False

    def stop_after_deadline() -> int:
        nonlocal timed_out
        timed_out = time.monotonic() >= deadline
        return int(timed_out)

    connection.set_progress_handler(stop_after_deadline, 100)
    try:
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(_REPLAY_MAX_RESULT_ROWS + 1)
        if len(rows) > _REPLAY_MAX_RESULT_ROWS:
            raise QueryResourceLimitError(
                f"replay query returned more than the {_REPLAY_MAX_RESULT_ROWS}-row limit"
            )
    except sqlite3.OperationalError as error:
        if timed_out or "interrupted" in str(error).lower():
            raise QueryTimeoutError(
                f"replay query exceeded the {_REPLAY_TIMEOUT_SECONDS:g}-second budget"
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)

    return QueryResult(
        columns=[ResultColumn(name=str(item[0])) for item in cursor.description or ()],
        rows=[[canonicalize_sqlite_value(value) for value in row] for row in rows],
    )


_REPLAY_DENIED_ACTIONS = frozenset(
    getattr(sqlite3, name)
    for name in (
        "SQLITE_ALTER_TABLE",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DELETE",
        "SQLITE_DETACH",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_DROP_VTABLE",
        "SQLITE_REINDEX",
    )
)


def _replay_fixture_authorizer(
    action: int,
    argument_1: str | None,
    argument_2: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    """Allow generated DDL/inserts while denying external or executable effects."""
    del database_name, trigger_name
    if action in _REPLAY_DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and (argument_1 or "").lower() not in {
        "foreign_keys",
        "defer_foreign_keys",
    }:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (argument_2 or "").lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay an isitright SQLite counterexample")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = replay_fixture(arguments.report, arguments.fixture)
    except Exception as error:
        print(f"replay error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["reproduced"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
