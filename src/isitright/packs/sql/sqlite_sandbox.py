"""Disposable SQLite copies for safe query execution and generated-state search."""

from __future__ import annotations

import base64
import sqlite3
import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from isitright.packs.sql.models import CanonicalValue, CanonicalValueKind, QueryResult, ResultColumn
from isitright.packs.sql.sqlite_schema import DatabaseSchema, introspect_schema


class DatabaseInputError(ValueError):
    """Raised when the supplied SQLite file cannot be safely inspected."""


class QueryExecutionError(RuntimeError):
    """Raised when SQLite cannot execute a validated query."""


class QueryTimeoutError(QueryExecutionError):
    """Raised when a query exceeds its execution budget."""


class QueryResourceLimitError(QueryExecutionError):
    """Raised when a query produces more rows than the configured cap."""


def foreign_key_problem(connection: sqlite3.Connection) -> str | None:
    """What ``PRAGMA foreign_key_check`` finds, in words, or None when the database is consistent.

    A violation names the child table, the parent table and how many rows have no parent. A
    ``foreign key mismatch`` is a declaration SQLite cannot enforce at all: the parent columns are
    neither the primary key nor covered by a unique index.
    """
    try:
        rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.OperationalError as error:
        if "foreign key mismatch" in str(error):
            return (
                f"{error}; the referenced columns are not the parent's primary key or unique, so "
                "SQLite cannot enforce the declaration"
            )
        raise
    if not rows:
        return None
    counts: dict[tuple[str, str], int] = {}
    for child, _rowid, parent, _index in rows:
        counts[(child, parent)] = counts.get((child, parent), 0) + 1
    shown = [f"{child} -> {parent} ({n} rows)" for (child, parent), n in sorted(counts.items())]
    more = f" and {len(shown) - 5} more" if len(shown) > 5 else ""
    return "rows without a parent: " + ", ".join(shown[:5]) + more


class SQLiteSandbox(AbstractContextManager["SQLiteSandbox"]):
    """An in-memory copy of a source database with query-only execution enabled."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.connection: sqlite3.Connection | None = None
        self.schema: DatabaseSchema | None = None

    def __enter__(self) -> Self:
        try:
            resolved = self.database.resolve(strict=True)
        except OSError as error:
            raise DatabaseInputError(f"database file is not readable: {self.database}") from error
        if not resolved.is_file():
            raise DatabaseInputError(f"database path is not a file: {self.database}")

        source: sqlite3.Connection | None = None
        memory: sqlite3.Connection | None = None
        try:
            source = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
            memory = sqlite3.connect(":memory:")
            source.backup(memory)
            memory.execute("PRAGMA foreign_keys = ON")
            self._verify_integrity(memory)
            self.schema = introspect_schema(memory)
            memory.execute("PRAGMA query_only = ON")
        except (sqlite3.Error, OSError) as error:
            if memory is not None:
                memory.close()
            raise DatabaseInputError(f"could not open SQLite database: {error}") from error
        finally:
            if source is not None:
                source.close()

        self.connection = memory
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    @staticmethod
    def _verify_integrity(connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            detail = "unknown" if integrity is None else str(integrity[0])
            raise DatabaseInputError(f"SQLite integrity check failed: {detail}")
        problem = foreign_key_problem(connection)
        if problem is not None:
            raise DatabaseInputError(f"SQLite foreign-key check failed: {problem}")

    def execute(
        self, sql: str, *, timeout_seconds: float, max_result_rows: int = 10_000
    ) -> QueryResult:
        """Execute one validated query with a monotonic progress-handler deadline."""
        if self.connection is None:
            raise RuntimeError("SQLiteSandbox must be entered before execution")
        return execute_query(
            self.connection, sql, timeout_seconds=timeout_seconds, max_result_rows=max_result_rows
        )


def execute_query(
    connection: sqlite3.Connection,
    sql: str,
    *,
    timeout_seconds: float,
    max_result_rows: int = 10_000,
) -> QueryResult:
    """Run one validated query under a read-only authorizer and a monotonic deadline."""
    deadline = time.monotonic() + timeout_seconds
    timed_out = False

    def stop_after_deadline() -> int:
        nonlocal timed_out
        timed_out = time.monotonic() >= deadline
        return int(timed_out)

    connection.set_progress_handler(stop_after_deadline, 100)
    connection.set_authorizer(_read_only_authorizer)
    try:
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(max_result_rows + 1)
        if len(rows) > max_result_rows:
            raise QueryResourceLimitError(
                f"query returned more than the {max_result_rows}-row limit"
            )
    except sqlite3.OperationalError as error:
        if timed_out or "interrupted" in str(error).lower():
            raise QueryTimeoutError(
                f"query exceeded the {timeout_seconds:g}-second budget"
            ) from error
        raise QueryExecutionError(str(error)) from error
    except sqlite3.Error as error:
        raise QueryExecutionError(str(error)) from error
    finally:
        connection.set_progress_handler(None, 0)
        connection.set_authorizer(None)

    columns = [ResultColumn(name=str(description[0])) for description in cursor.description or ()]
    return QueryResult(
        columns=columns,
        rows=[[canonicalize_sqlite_value(value) for value in row] for row in rows],
    )


def canonicalize_sqlite_value(value: Any) -> CanonicalValue:
    if value is None:
        return CanonicalValue(kind=CanonicalValueKind.NULL, value=None, engine_type="NULL")
    if isinstance(value, bool):
        return CanonicalValue(
            kind=CanonicalValueKind.INTEGER, value=int(value), engine_type="INTEGER"
        )
    if isinstance(value, int):
        return CanonicalValue(kind=CanonicalValueKind.INTEGER, value=value, engine_type="INTEGER")
    if isinstance(value, float):
        return CanonicalValue(kind=CanonicalValueKind.FLOAT, value=value, engine_type="REAL")
    if isinstance(value, str):
        return CanonicalValue(kind=CanonicalValueKind.TEXT, value=value, engine_type="TEXT")
    if isinstance(value, bytes):
        encoded = base64.b64encode(value).decode("ascii")
        return CanonicalValue(kind=CanonicalValueKind.BINARY, value=encoded, engine_type="BLOB")
    return CanonicalValue(
        kind=CanonicalValueKind.ENGINE_SPECIFIC,
        value=repr(value),
        engine_type=type(value).__name__,
    )


_DENIED_AUTHORIZE_ACTIONS = frozenset(
    getattr(sqlite3, name)
    for name in (
        "SQLITE_ALTER_TABLE",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
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
        "SQLITE_INSERT",
        "SQLITE_PRAGMA",
        "SQLITE_REINDEX",
        "SQLITE_SAVEPOINT",
        "SQLITE_TRANSACTION",
        "SQLITE_UPDATE",
    )
)


def _read_only_authorizer(
    action: int,
    argument_1: str | None,
    argument_2: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    """Deny state-changing opcodes even if parser validation is bypassed."""
    del argument_1, database_name, trigger_name
    if action in _DENIED_AUTHORIZE_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (argument_2 or "").lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK
