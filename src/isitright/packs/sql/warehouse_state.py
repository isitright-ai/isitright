"""The base world for a schema-only warehouse run: one row per table, nested values scoped.

Warehouse tables are rarely keyed and often huge, so the search starts from one small row per
table. A nested column a query reads is generated (an array holds one element, so that emptying it
is a change); a nested column no query reads is NULL if it can be, else its smallest valid value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from isitright.core.constraints import Constraint, OneOf, Pattern, Range
from isitright.packs.sql.mapping import SqlModel, domain_value
from isitright.packs.sql.schema import ColumnSchema, TableSchema
from isitright.packs.sql.state import DatabaseState, SqlValue, TableState
from isitright.packs.sql.typetree import minimal_value
from isitright.packs.sql.value_types import KEY_TYPES, generated_value


def warehouse_base_state(
    model: SqlModel,
    constraints: list[Constraint],
    referenced: set[tuple[str, str]],
    *,
    null_arrays: bool,
) -> DatabaseState:
    """One row per table. ``referenced``: the nested ``(table, column)`` pairs queries read."""
    domains = {c.path: c for c in constraints if isinstance(c, Range | OneOf | Pattern)}
    db = model.db
    keys: dict[str, SqlValue] = {}
    tables = []
    for table in db.tables:
        key = next((c for c in table.columns if c.primary_key_position), None)
        if key is not None:
            keys[table.name] = _scalar(key, domains, table)
    for table in db.tables:
        soft = {f.from_column: f for f in table.foreign_keys}
        row: list[SqlValue] = []
        for column in table.columns:
            if column.name in soft and soft[column.name].referenced_table in keys:
                row.append(keys[soft[column.name].referenced_table])
            elif column.type_tree is not None and column.type_tree.nested:
                row.append(_nested(column, (table.name, column.name) in referenced, null_arrays))
            elif column.primary_key_position:
                row.append(keys[table.name])
            else:
                row.append(_scalar(column, domains, table))
        columns = tuple(c.name for c in table.columns if c.hidden == 0)
        tables.append(TableState(table.name, columns, (tuple(row),)))
    return DatabaseState(tuple(tables))


def _nested(column: ColumnSchema, referenced: bool, null_arrays: bool) -> SqlValue:
    tree = column.type_tree
    assert tree is not None
    if referenced:
        return cast(SqlValue, minimal_value(tree, populate=True))
    nullable = not column.not_null and (null_arrays or tree.kind != "ARRAY")
    return None if nullable else cast(SqlValue, minimal_value(tree, populate=False))


def _scalar(column: ColumnSchema, domains: Mapping[str, Any], table: TableSchema) -> SqlValue:
    path = f"{table.name}.{column.name}"
    if path in domains and not column.primary_key_position:
        chosen = domain_value(domains[path].value_domain(path), column, 1)
        if chosen is not None:
            return chosen
    kind = column.declared_type.upper()
    if column.primary_key_position and kind not in KEY_TYPES:
        from isitright.packs.sql.typetree import leaf_value

        assert column.type_tree is not None
        return cast(SqlValue, leaf_value(column.type_tree))
    if kind == "BYTES":
        return b"" if column.not_null else None
    if kind == "TEXT" and column.primary_key_position:
        return "key-1"
    return generated_value(column, 1)
