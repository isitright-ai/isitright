"""The two-way mapping between SQL (DDL, rows) and the core's entity model.

Tables become collections, columns become fields, foreign keys become references, and unique
columns become `Unique` constraints. A table without a single-column primary key gets a synthetic
``__row`` key so its rows can be addressed as atoms; the key never reaches the engine.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, cast

from isitright.core.constraints import Constraint, Domain, OneOf, Pattern, Range, Unique
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, FieldType, RefSpec
from isitright.core.values import UnsupportedPattern, nth_pattern_value
from isitright.core.world import State
from isitright.packs.sql.schema import ColumnSchema, DatabaseSchema, TableSchema
from isitright.packs.sql.state import DatabaseState, SqlValue, TableState
from isitright.packs.sql.value_types import (
    FLOAT_TYPES,
    INTEGER_TYPES,
    KEY_TYPES,
    SYNTHETIC_TYPES,
    generated_value,
)

Dialect = Literal["sqlite", "postgres"]
ROW_KEY = "__row"


def _field_type(column: ColumnSchema, dialect: Dialect) -> FieldType:
    """Strict engines get exact types; SQLite is dynamically typed, so values are not policed."""
    if dialect == "sqlite":
        return "json"
    kind = column.declared_type.upper()
    if kind in INTEGER_TYPES:
        return "int"
    if kind in FLOAT_TYPES:
        return "float"
    if kind == "DECIMAL":
        return "decimal"
    if kind == "BOOLEAN":
        return "bool"
    if kind == "DATE":
        return "date"
    if kind in {"TIMESTAMP", "TIMESTAMPTZ"}:
        return "datetime"
    return "text"


@dataclass(frozen=True)
class SqlModel:
    db: DatabaseSchema
    dialect: Dialect
    schema: EntitySchema
    constraints: list[Constraint]
    synthetic_keys: frozenset[str]

    def key_of(self, table: str) -> str:
        return self.schema.collection(table).key

    def columns(self, table: str) -> tuple[str, ...]:
        return tuple(c.name for c in self.db.table(table).columns if c.hidden == 0)


def single_key(table: TableSchema) -> ColumnSchema | None:
    keys = [c for c in table.columns if c.primary_key_position and c.hidden == 0]
    return keys[0] if len(keys) == 1 else None


def build_model(db: DatabaseSchema, dialect: Dialect) -> SqlModel:
    collections: list[CollectionSpec] = []
    constraints: list[Constraint] = []
    synthetic: set[str] = set()
    for table in db.tables:
        key = single_key(table)
        fields = [
            FieldSpec(
                name=column.name,
                type=_field_type(column, dialect),
                nullable=not column.not_null and not column.primary_key_position,
            )
            for column in table.columns
            if column.hidden == 0
        ]
        if key is None:
            synthetic.add(table.name)
            fields.insert(0, FieldSpec(name=ROW_KEY, type="int"))
        references = []
        for foreign in table.foreign_keys:
            parent = db.table(foreign.referenced_table)
            parent_key = single_key(parent)
            targets_key = parent_key is not None and foreign.to_column in (None, parent_key.name)
            references.append(
                RefSpec(
                    field=foreign.from_column,
                    to=foreign.referenced_table,
                    enforced=targets_key and foreign.sequence == 0,
                )
            )
        collections.append(
            CollectionSpec(
                name=table.name,
                key=key.name if key is not None else ROW_KEY,
                fields=fields,
                references=references,
            )
        )
        for columns in table.unique_columns:
            if key is not None and columns == (key.name,):
                continue
            constraints.append(
                Unique(
                    name=f"unique:{table.name}({', '.join(columns)})",
                    tier="STRUCTURAL",
                    collection=table.name,
                    fields=list(columns),
                )
            )
    return SqlModel(
        db, dialect, EntitySchema(collections=collections), constraints, frozenset(synthetic)
    )


# --- values ---------------------------------------------------------------------------------------


def encode(value: SqlValue) -> Any:
    """A SQL value as a JSON-compatible state value."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if value is not None and not isinstance(value, bool | int | float | str):
        return value.isoformat()
    return value


def decode(value: Any, column: ColumnSchema) -> SqlValue:
    if isinstance(value, dict) and "$bytes" in value:
        return base64.b64decode(value["$bytes"])
    if column.declared_type.upper() == "DECIMAL" and isinstance(value, str | int | float):
        return Decimal(str(value))
    return cast(SqlValue, value)


def to_state(model: SqlModel, data: DatabaseState, params: dict[str, Any] | None = None) -> State:
    collections: dict[str, tuple[dict[str, Any], ...]] = {}
    for table in data.tables:
        rows = []
        for index, row in enumerate(table.rows):
            entity: dict[str, Any] = {}
            if table.name in model.synthetic_keys:
                entity[ROW_KEY] = index + 1
            entity.update({c: encode(v) for c, v in zip(table.columns, row, strict=True)})
            rows.append(entity)
        collections[table.name] = tuple(rows)
    keys = {c.name: c.key for c in model.schema.collections}
    return State(collections, keys, params or {})


def to_database_state(model: SqlModel, state: State) -> DatabaseState:
    tables = []
    for table in model.db.tables:
        columns = model.columns(table.name)
        by_name = {c.name: c for c in table.columns}
        rows = tuple(
            tuple(decode(entity.get(c), by_name[c]) for c in columns)
            for entity in state.entities(table.name)
        )
        tables.append(TableState(table.name, columns, rows))
    return DatabaseState(tuple(tables))


# --- generated base states (schema-only runs) ----------------------------------------------------


def supported_for_generation(db: DatabaseSchema) -> bool:
    """The conservative subset the generator supports: single supported keys, simple references."""
    if not db.tables:
        return False
    names = {t.name for t in db.tables}
    for table in db.tables:
        keys = [c for c in table.columns if c.primary_key_position]
        if len(keys) != 1 or keys[0].declared_type.upper() not in KEY_TYPES:
            return False
        if any(c.hidden or c.declared_type.upper() not in SYNTHETIC_TYPES for c in table.columns):
            return False
        if len(db.tables) > 1 and any(
            f.referenced_table not in names or f.referenced_table == table.name or f.sequence != 0
            for f in table.foreign_keys
        ):
            return False
    return True


def domain_value(domain: Domain | None, column: ColumnSchema, ordinal: int) -> SqlValue | None:
    """A value inside a declared domain, else None to keep the conservative generated value."""
    if domain is None:
        return None
    if domain.pattern is not None:
        try:
            return nth_pattern_value(domain.pattern, ordinal)
        except UnsupportedPattern:
            return None
    if domain.values:
        usable = [v for v in domain.values if v is not None]
        return usable[min(ordinal, len(usable)) - 1] if usable else None
    kind = column.declared_type.upper()
    if kind in INTEGER_TYPES | FLOAT_TYPES | {"DECIMAL"}:
        low = domain.minimum
        if low is None and domain.maximum is not None:
            return int(domain.maximum) if kind in INTEGER_TYPES else float(domain.maximum)
        if low is not None:
            # One step above the minimum, so a generated row sits off the edge and a copy of it
            # with a NULL cannot hide behind equal values (SUM(a - b) against SUM(a) - SUM(b)).
            value = low + ordinal
            if domain.maximum is not None and value > domain.maximum:
                value = domain.maximum
            if kind in INTEGER_TYPES:
                return int(value)
            return Decimal(str(value)) if kind == "DECIMAL" else float(value)
    return None


def _default_value(column: ColumnSchema) -> SqlValue | None:
    """The column's literal DEFAULT, evaluated by SQLite, else None."""
    import sqlite3

    if column.default_sql is None:
        return None
    try:
        with sqlite3.connect(":memory:") as connection:
            return connection.execute(f"SELECT {column.default_sql}").fetchone()[0]  # type: ignore[no-any-return]
    except sqlite3.Error:
        return None


def generate_base_state(
    model: SqlModel, constraints: list[Constraint], ordinal_rows: int = 1
) -> DatabaseState | None:
    """One row per table with matching references, or None for an unsupported schema."""
    db = model.db
    if not supported_for_generation(db):
        return None
    domains = {c.path: c for c in constraints if isinstance(c, Range | OneOf | Pattern)}

    def key_value(table: TableSchema, column: ColumnSchema, ordinal: int) -> SqlValue:
        widths = [column.type_parameters[0]] if column.type_parameters else []
        if column.declared_type.upper() == "TEXT":
            for child in db.tables:
                for foreign in child.foreign_keys:
                    if foreign.referenced_table == table.name and foreign.to_column in (
                        None,
                        column.name,
                    ):
                        local = next(c for c in child.columns if c.name == foreign.from_column)
                        widths.extend(local.type_parameters[:1])
        if widths:
            from dataclasses import replace

            column = replace(column, type_parameters=(min(widths),))
        return generated_value(column, ordinal)

    tables = []
    for table in db.tables:
        foreign_columns = {f.from_column: f for f in table.foreign_keys}
        columns = tuple(c.name for c in table.columns)
        row: list[SqlValue] = []
        for column in table.columns:
            if column.name in foreign_columns:
                foreign = foreign_columns[column.name]
                parent = db.table(foreign.referenced_table)
                target = next(
                    (c for c in parent.columns if c.name == foreign.to_column),
                    next(c for c in parent.columns if c.primary_key_position),
                )
                row.append(key_value(parent, target, 1))
            elif column.primary_key_position:
                row.append(key_value(table, column, 1))
            else:
                chosen = _default_value(column)
                path = f"{table.name}.{column.name}"
                if chosen is None and path in domains:
                    chosen = domain_value(domains[path].value_domain(path), column, 1)
                row.append(generated_value(column, 1) if chosen is None else chosen)
        tables.append(TableState(table.name, columns, (tuple(row),)))
    return DatabaseState(tuple(tables))


# --- importers ------------------------------------------------------------------------------------


_CHECK_IN = r"\b{name}\b\s+IN\s*\(([^)]*)\)"
_CHECK_MIN = r"\b{name}\b\s*>=\s*(-?\d+(?:\.\d+)?)"


def import_sql_checks(model: SqlModel) -> list[Constraint]:
    """Simple SQL ``CHECK`` forms (``col IN (...)``, ``col >= n``) as generation hints.

    They guide value generation only (tier STRUCTURAL): the engine enforces the real constraint.
    """
    out: list[Constraint] = []
    for table in model.db.tables:
        if " CHECK" not in table.ddl.upper():
            continue
        for column in table.columns:
            name = re.escape(column.name)
            members = re.search(_CHECK_IN.format(name=name), table.ddl, re.IGNORECASE)
            if members:
                values: list[Any] = []
                for text, number in re.findall(r"'([^']*)'|(-?\d+(?:\.\d+)?)", members.group(1)):
                    values.append(text if text else float(number) if "." in number else int(number))
                if values:
                    out.append(
                        OneOf(
                            name=f"check:{table.name}.{column.name}",
                            tier="STRUCTURAL",
                            path=f"{table.name}.{column.name}",
                            values=values,
                        )
                    )
                continue
            lower = re.search(_CHECK_MIN.format(name=name), table.ddl, re.IGNORECASE)
            if lower:
                text = lower.group(1)
                out.append(
                    Range(
                        name=f"check:{table.name}.{column.name}",
                        tier="STRUCTURAL",
                        path=f"{table.name}.{column.name}",
                        min=float(text) if "." in text else int(text),
                    )
                )
    return out


def import_json_schema(model: SqlModel, schema: dict[str, Any]) -> list[Constraint]:
    """Per-column facts of a JSON Schema over ``{table: [rows]}`` as core constraints.

    Reads ``properties.<table>.items.properties.<column>`` with ``minimum``, ``maximum``,
    ``enum`` and ``const``. The whole schema is still checked as a rule that generation cannot
    read; these constraints only steer value generation and boundary choice.
    """
    out: list[Constraint] = []
    tables = schema.get("properties", {})
    if not isinstance(tables, dict):
        return out
    for table in model.db.tables:
        items = (tables.get(table.name) or {}).get("items", {})
        columns = items.get("properties", {}) if isinstance(items, dict) else {}
        for column in table.columns:
            facts = columns.get(column.name) if isinstance(columns, dict) else None
            if not isinstance(facts, dict):
                continue
            path = f"{table.name}.{column.name}"
            if "const" in facts:
                out.append(OneOf(name=f"domain:{path}", path=path, values=[facts["const"]]))
            elif isinstance(facts.get("enum"), list):
                out.append(OneOf(name=f"domain:{path}", path=path, values=list(facts["enum"])))
            elif "minimum" in facts or "maximum" in facts:
                out.append(
                    Range(
                        name=f"domain:{path}",
                        path=path,
                        min=facts.get("minimum"),
                        max=facts.get("maximum"),
                    )
                )
            if isinstance(facts.get("pattern"), str):
                out.append(
                    Pattern(name=f"domain:{path}:pattern", path=path, regex=facts["pattern"])
                )
    return out


def fallback_base_state(model: SqlModel, constraints: list[Constraint]) -> DatabaseState:
    """One plausible row per table for SQLite schemas the strict generator does not support.

    Composite keys, BLOB columns and defaults are allowed here; the engine still validates every
    state, so a row it rejects costs an attempt, never a wrong result.
    """
    import sqlite3

    domains = {c.path: c for c in constraints if isinstance(c, Range | OneOf | Pattern)}
    values: dict[str, dict[str, SqlValue]] = {}

    def default_of(column: ColumnSchema) -> SqlValue | None:
        if column.default_sql is None:
            return None
        try:
            with sqlite3.connect(":memory:") as connection:
                return connection.execute(f"SELECT {column.default_sql}").fetchone()[0]  # type: ignore[no-any-return]
        except sqlite3.Error:
            return None

    def build(table: TableSchema) -> tuple[SqlValue, ...]:
        foreign = {f.from_column: f for f in table.foreign_keys}
        row: list[SqlValue] = []
        for column in table.columns:
            kind = column.declared_type.upper()
            if column.name in foreign and foreign[column.name].referenced_table in values:
                parent = values[foreign[column.name].referenced_table]
                target = foreign[column.name].to_column
                row.append(parent.get(target) if target in parent else next(iter(parent.values())))
                continue
            chosen = default_of(column) if not column.primary_key_position else None
            path = f"{table.name}.{column.name}"
            if chosen is None and path in domains:
                chosen = domain_value(domains[path].value_domain(path), column, 1)
            if chosen is None:
                if column.primary_key_position:
                    chosen = f"key-{1}" if kind in {"TEXT", "UUID", ""} or "CHAR" in kind else 1
                elif any(t in kind for t in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")):
                    chosen = 2
                elif "BLOB" in kind:
                    chosen = b""
                elif column.not_null:
                    chosen = "A"
            row.append(chosen)
        values[table.name] = {c.name: v for c, v in zip(table.columns, row, strict=True)}
        return tuple(row)

    ordered: list[TableSchema] = []
    pending = {t.name: t for t in model.db.tables}
    while pending:
        ready = [
            t
            for t in pending.values()
            if all(
                f.referenced_table not in pending or f.referenced_table == t.name
                for f in t.foreign_keys
            )
        ] or [next(iter(pending.values()))]
        for t in ready:
            ordered.append(t)
            pending.pop(t.name)
    built = {t.name: TableState(t.name, model.columns(t.name), (build(t),)) for t in ordered}
    return DatabaseState(tuple(built[t.name] for t in model.db.tables))
