"""Internal SQL schema representation shared by engine-specific readers.

The original DDL and declared types are retained: these structures describe
what was observed, not a promise that another engine has the same semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

from isitright.packs.sql.typetree import TypeNode


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
    type_tree: TypeNode | None = None
    """The declared type as a tree; set for warehouse columns (scalars and nested types)."""
    description: str | None = None


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
    qualified: str | None = None
    """The name as written in the DDL (``project.dataset.table``); `name` is its last part."""
    engine_ddl: str | None = None
    """DDL for the emulating engine, when the declared DDL is not in its dialect."""
    partition_columns: tuple[str, ...] = ()
    declared_keys: tuple[tuple[str, ...], ...] = ()
    """Keys the DDL declares without enforcing them (BigQuery ``NOT ENFORCED``)."""
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseSchema:
    tables: tuple[TableSchema, ...]

    def table(self, name: str) -> TableSchema:
        """Return a table by exact name."""
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)
