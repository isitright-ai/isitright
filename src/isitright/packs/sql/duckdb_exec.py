"""DuckDB execution of PostgreSQL and warehouse programs: an emulation, never native evidence."""

from __future__ import annotations

import importlib
import threading

import sqlglot
from sqlglot.errors import ErrorLevel

from isitright.packs.sql.dialect_fidelity import catalog_of, translate_for_duckdb
from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.errors import StateRejected
from isitright.packs.sql.models import QueryResult
from isitright.packs.sql.postgres_ddl import Schema, _ordered_schema_tables
from isitright.packs.sql.postgres_server import _constraint_error, _result
from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
from isitright.packs.sql.state import DatabaseState, TableState
from isitright.packs.sql.state_loader import load_state
from isitright.packs.sql.typetree import to_engine


def engine_state(schema: DatabaseSchema, state: DatabaseState) -> DatabaseState:
    """The state with nested values as python values a driver binds (maps as mappings, dates)."""
    tables = []
    for table in state.tables:
        trees = {
            c.name: c.type_tree for c in schema.table(table.name).columns if c.type_tree is not None
        }
        nested = [i for i, name in enumerate(table.columns) if name in trees and trees[name].nested]
        if not nested:
            tables.append(table)
            continue
        rows = tuple(
            tuple(
                to_engine(trees[table.columns[i]], v) if i in nested else v
                for i, v in enumerate(row)
            )
            for row in table.rows
        )
        tables.append(TableState(table.name, table.columns, rows))
    return DatabaseState(tuple(tables))


def _execute_duckdb(
    schema: Schema,
    state: DatabaseState,
    reference: str,
    candidate: str,
    timeout_seconds: float,
    max_rows: int,
    warehouse: Dialect | None = None,
) -> tuple[QueryResult, QueryResult, str]:
    duckdb = importlib.import_module("duckdb")
    catalog = catalog_of(schema.database)
    with duckdb.connect(":memory:", config={"enable_external_access": "false"}) as connection:
        if warehouse is not None:
            # BigQuery and Presto read timestamps in UTC; DuckDB would use the machine's zone.
            connection.execute("SET TimeZone = 'UTC'")
        for table in _ordered_schema_tables(schema.database):
            if warehouse is not None:
                assert table.engine_ddl is not None
                connection.execute(table.engine_ddl)
            else:
                connection.execute(
                    sqlglot.transpile(
                        table.ddl,
                        read="postgres",
                        write="duckdb",
                        unsupported_level=ErrorLevel.RAISE,
                    )[0]
                )
        try:
            load_state(
                schema.database,
                engine_state(schema.database, state) if warehouse is not None else state,
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
                if warehouse is None:
                    return _result(
                        connection.execute(translate_for_duckdb(query, catalog).sql), max_rows
                    )
                try:
                    return _result(connection.execute(query), max_rows, dialect=warehouse)
                except duckdb.Error as error:  # a data-dependent query error is a per-world result
                    raise QueryExecutionError(f"{type(error).__name__}: {error}") from error
            finally:
                timer.cancel()
                timer.join()

        left, right = execute_one(reference), execute_one(candidate)
        return left, right, str(duckdb.__version__)
