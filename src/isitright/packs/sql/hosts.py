"""SQL hosts: run a reference and a candidate program on one world, with stated fidelity.

SQLite and PostgreSQL run natively on disposable instances (`NATIVE_ISOLATED`); DuckDB runs
translated PostgreSQL and is `EMULATED`: a candidate generator, not native evidence.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from decimal import Decimal
from types import TracebackType
from typing import Any, Self

from isitright.core.hosts import Fidelity
from isitright.packs.sql.duckdb_exec import _execute_duckdb
from isitright.packs.sql.errors import StateRejected
from isitright.packs.sql.models import QueryResult
from isitright.packs.sql.postgres_ddl import Schema
from isitright.packs.sql.postgres_server import _execute_postgres, _postgres_server
from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError, execute_query
from isitright.packs.sql.state import DatabaseState
from isitright.packs.sql.state_loader import load_state


class SqlHost:
    """Common surface: a fidelity, an engine label, and `run_pair` on a data-only state."""

    fidelity: Fidelity
    engine: str
    version: str | None = None

    def run_pair(
        self,
        state: DatabaseState,
        reference_sql: str,
        candidate_sql: str,
        *,
        timeout_seconds: float,
        max_result_rows: int,
    ) -> tuple[QueryResult, QueryResult]:
        raise NotImplementedError


class SqliteHost(SqlHost):
    """A fresh in-memory SQLite database per world: DDL, rows, `query_only`, an authorizer."""

    fidelity = Fidelity.NATIVE_ISOLATED
    engine = "sqlite"

    def __init__(self, schema: DatabaseSchema) -> None:
        self.schema = schema
        self.version = sqlite3.sqlite_version

    def _load(self, state: DatabaseState) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            for table in self.schema.tables:
                connection.execute(table.ddl)
            for table in self.schema.tables:
                for ddl in table.index_ddls:
                    connection.execute(ddl)
            try:
                connection.execute("BEGIN")
                connection.execute("PRAGMA defer_foreign_keys = ON")
                # sqlite3 cannot bind Decimal; NUMERIC affinity converts the text back.
                load_state(
                    self.schema,
                    state,
                    execute=lambda sql, row: connection.execute(
                        sql, tuple(str(v) if isinstance(v, Decimal) else v for v in row)
                    ),
                    parameter="?",
                    allow_cycles=True,
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                raise StateRejected(str(error)) from error
            except sqlite3.Error as error:
                raise StateRejected(f"{type(error).__name__}: {error}") from error
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise StateRejected("foreign-key check failed")
            connection.execute("PRAGMA query_only = ON")
        except BaseException:
            connection.close()
            raise
        return connection

    def run_pair(
        self,
        state: DatabaseState,
        reference_sql: str,
        candidate_sql: str,
        *,
        timeout_seconds: float,
        max_result_rows: int,
    ) -> tuple[QueryResult, QueryResult]:
        connection = self._load(state)
        try:
            return (
                execute_query(
                    connection,
                    reference_sql,
                    timeout_seconds=timeout_seconds,
                    max_result_rows=max_result_rows,
                ),
                execute_query(
                    connection,
                    candidate_sql,
                    timeout_seconds=timeout_seconds,
                    max_result_rows=max_result_rows,
                ),
            )
        finally:
            connection.close()

    def run_each(
        self,
        state: DatabaseState,
        queries: list[str],
        *,
        timeout_seconds: float,
        max_result_rows: int,
    ) -> list[QueryResult | QueryExecutionError]:
        """Run every query even if an earlier one fails, so each failure is reported."""
        connection = self._load(state)
        try:
            out: list[QueryResult | QueryExecutionError] = []
            for sql in queries:
                try:
                    out.append(
                        execute_query(
                            connection,
                            sql,
                            timeout_seconds=timeout_seconds,
                            max_result_rows=max_result_rows,
                        )
                    )
                except QueryExecutionError as error:
                    out.append(error)
            return out
        finally:
            connection.close()


class PostgresHost(SqlHost, AbstractContextManager["PostgresHost"]):
    """One temporary PostgreSQL server for the whole audit; temporary tables per world."""

    fidelity = Fidelity.NATIVE_ISOLATED
    engine = "postgres"

    def __init__(self, schema: Schema, server: tuple[Any, str] | None = None) -> None:
        self.schema = schema
        self._server = server
        self._context: AbstractContextManager[tuple[Any, str]] | None = None
        self._backend: Any = None
        self._uri = ""

    def __enter__(self) -> Self:
        if self._server is None:
            self._context = _postgres_server()
            self._backend, self._uri = self._context.__enter__()
        else:
            self._backend, self._uri = self._server
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is not None:
            self._context.__exit__(exc_type, exc_value, traceback)
            self._context = None

    def run_pair(
        self,
        state: DatabaseState,
        reference_sql: str,
        candidate_sql: str,
        *,
        timeout_seconds: float,
        max_result_rows: int,
    ) -> tuple[QueryResult, QueryResult]:
        left, right, version = _execute_postgres(
            self._backend,
            self._uri,
            self.schema,
            state,
            reference_sql,
            candidate_sql,
            timeout_seconds,
            max_result_rows,
        )
        self.version = version
        return left, right


class DuckdbHost(SqlHost):
    fidelity = Fidelity.EMULATED
    engine = "duckdb"

    def __init__(self, schema: Schema) -> None:
        self.schema = schema

    def run_pair(
        self,
        state: DatabaseState,
        reference_sql: str,
        candidate_sql: str,
        *,
        timeout_seconds: float,
        max_result_rows: int,
    ) -> tuple[QueryResult, QueryResult]:
        left, right, version = _execute_duckdb(
            self.schema, state, reference_sql, candidate_sql, timeout_seconds, max_result_rows
        )
        self.version = version
        return left, right
