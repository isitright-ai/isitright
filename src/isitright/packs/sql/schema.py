"""Internal SQL schema representation shared by engine-specific readers.

The original DDL and declared types are retained: these structures describe
what was observed, not a promise that another engine has the same semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    cid: int
    name: str
    declared_type: str
    not_null: bool
    default_sql: str | None
    primary_key_position: int
    hidden: int
    type_parameters: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ForeignKeySchema:
    id: int
    sequence: int
    referenced_table: str
    from_column: str
    to_column: str | None
    on_update: str
    on_delete: str
    match: str


@dataclass(frozen=True, slots=True)
class TableSchema:
    name: str
    ddl: str
    columns: tuple[ColumnSchema, ...]
    foreign_keys: tuple[ForeignKeySchema, ...]
    unique_columns: tuple[tuple[str, ...], ...]
    index_ddls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatabaseSchema:
    tables: tuple[TableSchema, ...]

    def table(self, name: str) -> TableSchema:
        """Return a table by exact name."""
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)
