"""Load data-only SQL states into an already isolated engine connection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.state import DatabaseState, TableState


class StateLoadError(ValueError):
    """The state cannot safely be loaded using the supported schema subset."""


def load_state(
    schema: DatabaseSchema,
    state: DatabaseState,
    *,
    execute: Callable[[str, tuple[Any, ...]], Any],
    parameter: Literal["?", "%s"],
    allow_cycles: bool = False,
) -> None:
    """Insert complete rows in foreign-key order with bound, never interpolated, values.

    The caller owns isolation, transaction boundaries, and schema creation. Cyclic
    dependencies are deliberately unsupported; the target engine enforces all
    actual constraints. Validate the complete plan before executing any insert.
    """
    if parameter not in ("?", "%s"):
        raise StateLoadError("unsupported parameter style")
    by_name = {table.name: table for table in state.tables}
    dependencies: dict[str, set[str]] = {}
    for table in state.tables:
        try:
            table_schema = schema.table(table.name)
        except KeyError as error:
            raise StateLoadError(f"unknown table: {table.name}") from error
        columns = tuple(column.name for column in table_schema.columns if column.hidden == 0)
        if table.columns != columns or not columns:
            raise StateLoadError(f"columns do not match schema for table: {table.name}")
        dependencies[table.name] = {
            key.referenced_table
            for key in table_schema.foreign_keys
            if key.referenced_table in by_name and table.rows and by_name[key.referenced_table].rows
        }

    ordered: list[TableState] = []
    pending = dict(dependencies)
    while pending:
        ready = [name for name, parents in pending.items() if not parents]
        if not ready and allow_cycles:
            # The caller defers foreign-key checks to commit (SQLite) and verifies afterwards.
            ready = [next(iter(pending))]
        if not ready:
            raise StateLoadError("cyclic foreign-key dependencies are unsupported")
        for name in ready:
            ordered.append(by_name[name])
            del pending[name]
        for parents in pending.values():
            parents.difference_update(ready)

    for table in ordered:
        if not table.rows:
            continue
        names = ", ".join(_quote(column) for column in table.columns)
        markers = ", ".join(parameter for _ in table.columns)
        statement = f"INSERT INTO {_quote(table.name)} ({names}) VALUES ({markers})"
        for row in table.rows:
            execute(statement, row)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
