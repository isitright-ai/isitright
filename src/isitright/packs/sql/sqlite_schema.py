"""SQLite schema introspection used by execution and later search stages."""

from __future__ import annotations

import re
import sqlite3

# Re-export the existing names so internal and downstream imports remain valid.
from isitright.packs.sql.schema import (
    ColumnSchema as ColumnSchema,
)
from isitright.packs.sql.schema import (
    DatabaseSchema as DatabaseSchema,
)
from isitright.packs.sql.schema import (
    ForeignKeySchema as ForeignKeySchema,
)
from isitright.packs.sql.schema import (
    TableSchema as TableSchema,
)

_TYPE_PATTERN = re.compile(r"\s*([A-Za-z][A-Za-z ]*?)\s*(?:\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?\s*")
_TEXT_ALIASES = frozenset(
    {"VARCHAR", "CHAR", "CHARACTER", "NVARCHAR", "NCHAR", "CHARACTER VARYING"}
)


def parse_declared_type(declared: str) -> tuple[str, tuple[int, ...]]:
    """Split a SQLite declared type into the shared type name and its parameters.

    Only length and precision/scale forms with the ranges the PostgreSQL reader accepts are
    normalized (VARCHAR(n) to TEXT, NUMERIC(p, s) to DECIMAL); anything else stays as declared,
    which the shared generator treats as unsupported.
    """
    match = _TYPE_PATTERN.fullmatch(declared)
    if match is None:
        return declared, ()
    base = " ".join(match.group(1).upper().split())
    parameters = tuple(int(group) for group in match.groups()[1:] if group is not None)
    if base in _TEXT_ALIASES:
        if len(parameters) > 1 or (parameters and not 1 <= parameters[0] <= 10000):
            return declared, ()
        return "TEXT", parameters
    if base in {"NUMERIC", "DECIMAL"}:
        if parameters and not (
            1 <= parameters[0] <= 1000
            and (len(parameters) == 1 or 0 <= parameters[1] <= parameters[0])
        ):
            return declared, ()
        return "DECIMAL", parameters
    return declared, ()


def _column(row: tuple[object, ...]) -> ColumnSchema:
    declared_type, type_parameters = parse_declared_type(str(row[2]))
    return ColumnSchema(
        cid=int(str(row[0])),
        name=str(row[1]),
        declared_type=declared_type,
        not_null=bool(row[3]),
        default_sql=None if row[4] is None else str(row[4]),
        primary_key_position=int(str(row[5])),
        hidden=int(str(row[6])),
        type_parameters=type_parameters,
    )


def introspect_schema(connection: sqlite3.Connection) -> DatabaseSchema:
    """Read user-table DDL, columns, and foreign keys deterministically."""
    table_rows = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_schema
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    tables: list[TableSchema] = []
    for name, ddl in table_rows:
        column_rows = connection.execute(
            'SELECT cid, name, type, "notnull", dflt_value, pk, hidden '
            "FROM pragma_table_xinfo(?) ORDER BY cid",
            (name,),
        ).fetchall()
        foreign_key_rows = connection.execute(
            'SELECT id, seq, "table", "from", "to", on_update, on_delete, match '
            "FROM pragma_foreign_key_list(?) ORDER BY id, seq",
            (name,),
        ).fetchall()
        unique_columns: list[tuple[str, ...]] = []
        index_ddls: list[str] = []
        for index_row in connection.execute(
            'SELECT name, "unique" FROM pragma_index_list(?) ORDER BY seq', (name,)
        ).fetchall():
            if not bool(index_row[1]):
                continue
            columns = tuple(
                str(row[2])
                for row in connection.execute(
                    "SELECT seqno, cid, name FROM pragma_index_info(?) ORDER BY seqno",
                    (index_row[0],),
                ).fetchall()
                if row[2] is not None
            )
            if columns:
                unique_columns.append(columns)
            index_ddl = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type = 'index' AND name = ?",
                (index_row[0],),
            ).fetchone()
            if index_ddl is not None and index_ddl[0] is not None:
                index_ddls.append(str(index_ddl[0]))
        tables.append(
            TableSchema(
                name=str(name),
                ddl=str(ddl),
                columns=tuple(_column(row) for row in column_rows),
                foreign_keys=tuple(
                    ForeignKeySchema(
                        id=int(row[0]),
                        sequence=int(row[1]),
                        referenced_table=str(row[2]),
                        from_column=str(row[3]),
                        to_column=None if row[4] is None else str(row[4]),
                        on_update=str(row[5]),
                        on_delete=str(row[6]),
                        match=str(row[7]),
                    )
                    for row in foreign_key_rows
                ),
                unique_columns=tuple(unique_columns),
                index_ddls=tuple(sorted(index_ddls)),
            )
        )
    return DatabaseSchema(tables=tuple(tables))
