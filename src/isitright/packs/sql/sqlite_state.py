"""Read SQLite state into the shared SQL-world representation."""

from __future__ import annotations

import sqlite3

from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.state import DatabaseState, TableState


def snapshot_sqlite(connection: sqlite3.Connection, schema: DatabaseSchema) -> DatabaseState:
    """Read visible columns only, matching the existing SQLite domain snapshot."""
    tables = []
    for table in schema.tables:
        columns = tuple(column.name for column in table.columns if column.hidden == 0)
        names = ", ".join(_quote(name) for name in columns)
        rows = connection.execute(f"SELECT {names} FROM {_quote(table.name)}").fetchall()
        tables.append(TableState(table.name, columns, tuple(tuple(row) for row in rows)))
    return DatabaseState(tuple(tables))


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
