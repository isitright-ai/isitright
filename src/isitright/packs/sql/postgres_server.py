"""Native PostgreSQL server management and execution (temporary instance per audit).

Includes the Windows temp-directory handling: on Python 3.12.4+, mode=0o700 creates a restrictive
ACL that PostgreSQL's de-elevated process cannot traverse.
"""

from __future__ import annotations

import importlib
import math
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from isitright.packs.sql.errors import StateRejected
from isitright.packs.sql.models import CanonicalValue, CanonicalValueKind, QueryResult, ResultColumn
from isitright.packs.sql.postgres_ddl import Schema, _ordered_schema_tables
from isitright.packs.sql.sqlite_sandbox import canonicalize_sqlite_value
from isitright.packs.sql.state import DatabaseState
from isitright.packs.sql.state_loader import load_state


def _constraint_error(error: Exception, engine: Literal["postgres", "duckdb"]) -> bool:
    """Classify load-time integrity and numeric-range violations, not query errors."""
    sqlstate = getattr(error, "sqlstate", None)
    if (
        engine == "postgres"
        and isinstance(sqlstate, str)
        and (sqlstate.startswith("23") or sqlstate in {"22001", "22003"})
    ):
        return True
    return engine == "duckdb" and type(error).__name__ in {
        "ConstraintException",
        "ConversionException",
    }


def _result(cursor: Any, limit: int) -> QueryResult:
    rows = cursor.fetchmany(limit + 1)
    if len(rows) > limit:
        raise RuntimeError(f"query exceeded {limit} result rows")

    def canonical(value: Any) -> CanonicalValue:
        if isinstance(value, bool):
            return CanonicalValue(kind=CanonicalValueKind.BOOLEAN, value=value)
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise RuntimeError("non-finite numeric result is unsupported")
            return CanonicalValue(kind=CanonicalValueKind.DECIMAL, value=str(value))
        if isinstance(value, datetime):
            return CanonicalValue(kind=CanonicalValueKind.DATETIME, value=value.isoformat())
        if isinstance(value, date):
            return CanonicalValue(kind=CanonicalValueKind.DATE, value=value.isoformat())
        if isinstance(value, uuid.UUID):
            return CanonicalValue(
                kind=CanonicalValueKind.ENGINE_SPECIFIC, value=str(value), engine_type="UUID"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise RuntimeError("non-finite numeric result is unsupported")
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise RuntimeError(f"unsupported result type: {type(value).__name__}")
        return canonicalize_sqlite_value(value)

    return QueryResult(
        columns=[ResultColumn(name=str(col[0])) for col in cursor.description or ()],
        rows=[[canonical(value) for value in row] for row in rows],
    )


@contextmanager
def _temporary_postgres_directory() -> Iterator[Path]:
    """Create a temporary directory that PostgreSQL can access on Windows."""
    directory = Path(tempfile.gettempdir()) / f"isitright-pg-{uuid.uuid4().hex}"
    # On Python 3.12.4+, mode=0o700 creates a restrictive Windows ACL that
    # PostgreSQL's de-elevated process cannot traverse. Windows ignores other
    # modes, so use the default there and retain owner-only access on POSIX.
    if os.name == "nt":
        directory.mkdir()
    else:
        directory.mkdir(mode=0o700)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


@contextmanager
def _postgres_server() -> Iterator[tuple[Any, str]]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError("the bundled PostgreSQL server must not run as root")
    embedded = importlib.import_module("embedded_postgres")
    psycopg = importlib.import_module("psycopg")
    with (
        _temporary_postgres_directory() as directory,
        embedded.get_server(directory / "data", cleanup_mode="stop") as server,
    ):
        yield psycopg, server.get_uri()


def _execute_postgres(
    psycopg: Any,
    uri: str,
    schema: Schema,
    state: DatabaseState,
    reference: str,
    candidate: str,
    timeout_seconds: float,
    max_rows: int,
) -> tuple[QueryResult, QueryResult, str]:
    with psycopg.connect(uri, autocommit=True) as connection:
        version = str(connection.execute("SHOW server_version").fetchone()[0])
        for table in _ordered_schema_tables(schema.database):
            connection.execute(table.ddl.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1))
        try:
            load_state(
                schema.database,
                state,
                execute=connection.execute,
                parameter="%s",
            )
        except Exception as error:
            if _constraint_error(error, "postgres"):
                raise StateRejected(str(error)) from error
            raise
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(max(1, int(timeout_seconds * 1000))),),
            )
            left = _result(connection.execute(reference), max_rows)
            right = _result(connection.execute(candidate), max_rows)
        return left, right, version
