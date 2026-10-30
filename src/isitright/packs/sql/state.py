"""Internal data-only snapshots of SQL database states.

Rows are sequences rather than sets: duplicate rows are meaningful in SQL.
Engine-specific serialization and loading belong to the execution adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

SqlValue = None | bool | int | float | str | bytes | Decimal | date | time | datetime


@dataclass(frozen=True, slots=True)
class TableState:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[SqlValue, ...], ...]

    def __post_init__(self) -> None:
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("duplicate column names")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("row width does not match columns")

    def records(self) -> list[dict[str, SqlValue]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]


@dataclass(frozen=True, slots=True)
class DatabaseState:
    tables: tuple[TableState, ...]

    def __post_init__(self) -> None:
        if len({table.name for table in self.tables}) != len(self.tables):
            raise ValueError("duplicate table names")

    def records(self) -> dict[str, list[dict[str, SqlValue]]]:
        return {table.name: table.records() for table in self.tables}
