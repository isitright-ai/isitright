"""DuckDB execution of PostgreSQL programs: a labeled emulation, never native evidence."""

from __future__ import annotations

import importlib
import threading

import sqlglot
from sqlglot.errors import ErrorLevel

from isitright.packs.sql.dialect_fidelity import catalog_of, translate_for_duckdb
from isitright.packs.sql.errors import StateRejected
from isitright.packs.sql.models import QueryResult
from isitright.packs.sql.postgres_ddl import Schema, _ordered_schema_tables
from isitright.packs.sql.postgres_server import _constraint_error, _result
from isitright.packs.sql.state import DatabaseState
from isitright.packs.sql.state_loader import load_state


def _execute_duckdb(
    schema: Schema,
    state: DatabaseState,
    reference: str,
    candidate: str,
    timeout_seconds: float,
    max_rows: int,
) -> tuple[QueryResult, QueryResult, str]:
    duckdb = importlib.import_module("duckdb")
    catalog = catalog_of(schema.database)
    with duckdb.connect(":memory:", config={"enable_external_access": "false"}) as connection:
        for table in _ordered_schema_tables(schema.database):
            connection.execute(
                sqlglot.transpile(
                    table.ddl, read="postgres", write="duckdb", unsupported_level=ErrorLevel.RAISE
                )[0]
            )
        try:
            load_state(
                schema.database,
                state,
                execute=connection.execute,
                parameter="?",
            )
        except Exception as error:
            if _constraint_error(error, "duckdb"):
                raise StateRejected(str(error)) from error
            raise

        def execute_one(query: str) -> QueryResult:
            timer = threading.Timer(timeout_seconds, connection.interrupt)
            timer.start()
            try:
                translated = translate_for_duckdb(query, catalog).sql
                return _result(connection.execute(translated), max_rows)
            finally:
                timer.cancel()
                timer.join()

        left, right = execute_one(reference), execute_one(candidate)
        return left, right, str(duckdb.__version__)
