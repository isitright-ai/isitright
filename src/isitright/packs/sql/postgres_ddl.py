"""PostgreSQL DDL and query parsing for the SQL pack.

The supported SQL and DDL are intentionally small. This is not a general SQL sandbox or a
PostgreSQL compatibility layer. Unsupported input raises `SqlInputError`.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlglot
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.schema import ColumnSchema, DatabaseSchema, ForeignKeySchema, TableSchema
from isitright.packs.sql.state import DatabaseState, SqlValue
from isitright.packs.sql.value_types import FLOAT_TYPES, INTEGER_TYPES, KEY_TYPES

_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


_ALLOWED_QUERY_NODES = {
    "Select",
    "From",
    "Table",
    "Identifier",
    "Column",
    "Where",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "EQ",
    "NEQ",
    "And",
    "Or",
    "Not",
    "Is",
    "Null",
    "Literal",
    "Neg",
    "Count",
    "Sum",
    "Sub",
    "Add",
    "Mul",
    "Div",
    "Star",
    "Paren",
    "Alias",
    "Distinct",
    "Group",
    "Order",
    "Ordered",
    "Limit",
    "Max",
    "Min",
    "Avg",
    "Join",
    "TableAlias",
    "With",
    "CTE",
    "Subquery",
    "Exists",
    "In",
    "Case",
    "If",
    "Having",
    "Union",
    "Intersect",
    "Except",
    "Between",
    "Boolean",
    "Like",
    "ILike",
    "Window",
    "WindowSpec",
    "RowNumber",
    "Rank",
    "DenseRank",
    "Coalesce",
    "Cast",
    "DataType",
}


@dataclass(frozen=True)
class Schema:
    """Single-table compatibility view over the shared schema representation."""

    database: DatabaseSchema

    @property
    def table(self) -> str:
        return self.database.tables[0].name

    @property
    def columns(self) -> tuple[ColumnSchema, ...]:
        return self.database.tables[0].columns

    @property
    def ddl(self) -> str:
        return ";\n".join(table.ddl for table in _ordered_schema_tables(self.database))


def _ordered_schema_tables(schema: DatabaseSchema) -> list[TableSchema]:
    pending = {table.name: table for table in schema.tables}
    ordered: list[TableSchema] = []
    while pending:
        ready = [
            table
            for table in pending.values()
            if not any(key.referenced_table in pending for key in table.foreign_keys)
        ]
        if not ready:
            raise SqlInputError("cyclic foreign-key dependencies are unsupported")
        for table in ready:
            ordered.append(table)
            del pending[table.name]
    return ordered


def _literal(column: ColumnSchema, value: SqlValue) -> str:
    """Render only values of the declared supported type, with safe quoting."""
    if value is None:
        return "NULL"
    kind = column.declared_type
    if kind in INTEGER_TYPES and type(value) is int:
        if not -(2**63) <= value < 2**63:
            raise SqlInputError("integer state value out of range")
        return str(value)
    if kind == "DECIMAL" and (type(value) is int or isinstance(value, Decimal)):
        number = Decimal(value)
        if not number.is_finite():
            raise SqlInputError("non-finite state value")
        return str(number)
    if kind in FLOAT_TYPES and (type(value) is int or type(value) is float):
        number_float = float(value)
        if not math.isfinite(number_float):
            raise SqlInputError("non-finite state value")
        return repr(number_float)
    if kind == "BOOLEAN" and isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if kind in {"TEXT", "UUID", "DATE", "TIMESTAMP", "TIMESTAMPTZ"} and isinstance(value, str):
        try:
            if kind == "UUID":
                uuid.UUID(value)
            elif kind == "DATE":
                date.fromisoformat(value)
            elif kind in {"TIMESTAMP", "TIMESTAMPTZ"}:
                parsed = datetime.fromisoformat(value)
                if (parsed.utcoffset() is not None) != (kind == "TIMESTAMPTZ"):
                    raise ValueError("timestamp time zone does not match type")
        except ValueError as error:
            raise SqlInputError(f"invalid {kind} state value") from error
        return "'" + value.replace("'", "''") + "'"
    raise SqlInputError(f"state value does not match {kind}")


def _state_sql(schema: Schema, rows: list[dict[str, SqlValue]]) -> str:
    if not rows:
        return ""
    names = ", ".join(f'"{column.name}"' for column in schema.columns)
    values = ", ".join(
        "(" + ", ".join(_literal(c, row[c.name]) for c in schema.columns) + ")" for row in rows
    )
    return f'INSERT INTO "{schema.table}" ({names}) VALUES {values}'


def _render_state(schema: Schema, state: DatabaseState) -> str:
    """Render only a validated state in the currently supported PostgreSQL subset."""
    by_name = {table.name: table for table in state.tables}
    if set(by_name) != {table.name for table in schema.database.tables}:
        raise SqlInputError("state tables do not match schema")
    statements = []
    for table_schema in _ordered_schema_tables(schema.database):
        table = by_name[table_schema.name]
        columns = tuple(column.name for column in table_schema.columns)
        if table.columns != columns:
            raise SqlInputError("state columns do not match schema")
        rows: list[dict[str, SqlValue]] = []
        for row in table.rows:
            for column, value in zip(table_schema.columns, row, strict=True):
                _literal(column, value)
            rows.append({name: value for name, value in zip(columns, row, strict=True)})
        sql = _state_sql(Schema(DatabaseSchema((table_schema,))), rows)
        if sql:
            statements.append(sql)
    return ";\n".join(statements)


def _validate_domain_schema(domain_schema: dict[str, Any] | None) -> None:
    if domain_schema is None:
        return

    def reject_remote_refs(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise SqlInputError("remote constraint references are unsupported")
                reject_remote_refs(item)
        elif isinstance(value, list):
            for item in value:
                reject_remote_refs(item)

    reject_remote_refs(domain_schema)
    try:
        Draft202012Validator.check_schema(domain_schema)
    except SchemaError as error:
        raise SqlInputError(f"invalid domain constraints: {error.message}") from error


def _parse_one(sql: str) -> exp.Expression:
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="postgres") if statement]
    except ParseError as error:
        raise SqlInputError(f"SQL parse error: {error}") from error
    if len(statements) != 1:
        raise SqlInputError("exactly one SQL statement is required")
    return statements[0]


def _name(value: str) -> str:
    if not _NAME.fullmatch(value):
        raise SqlInputError("only lowercase unqualified identifiers are supported")
    return value


def parse_schema(ddl: str) -> Schema:
    """Accept only one simple table, one integer primary key, and basic columns."""
    return Schema(DatabaseSchema(tables=(_parse_table(_parse_one(ddl), references=False),)))


def _parse_table(tree: exp.Expression, *, references: bool) -> TableSchema:
    if not isinstance(tree, exp.Create) or tree.args.get("kind") != "TABLE":
        raise SqlInputError("expected one CREATE TABLE")
    if not isinstance(tree.this, exp.Schema) or not isinstance(tree.this.this, exp.Table):
        raise SqlInputError("expected explicit table columns")
    table = tree.this.this
    if (
        table.db
        or table.catalog
        or any(tree.args.get(k) for k in ("replace", "exists", "expression", "properties"))
    ):
        raise SqlInputError("qualified tables and CREATE options are unsupported")
    name = _name(table.name)
    definitions = list(tree.this.expressions)
    table_keys = [item for item in definitions if isinstance(item, exp.PrimaryKey)]
    if table_keys and not references:
        raise SqlInputError("table-level constraints are unsupported")
    if len(table_keys) > 1 or any(
        len(item.expressions) != 1
        or not isinstance(item.expressions[0], exp.Identifier)
        or item.args.get("options")
        for item in table_keys
    ):
        raise SqlInputError("only single-column primary keys are supported")
    table_key = _name(table_keys[0].expressions[0].name) if table_keys else None
    columns: list[ColumnSchema] = []
    foreign_keys: list[ForeignKeySchema] = []
    unique_columns: list[tuple[str, ...]] = []

    def add_reference(column_name: str, ref: exp.Reference) -> None:
        target = ref.this
        if (
            ref.args.get("options")
            or ref.args.get("expressions")
            or not isinstance(target, exp.Schema)
            or not isinstance(target.this, exp.Table)
            or target.this.db
            or target.this.catalog
            or len(target.expressions) != 1
            or not isinstance(target.expressions[0], exp.Identifier)
        ):
            raise SqlInputError("unsupported foreign key")
        foreign_keys.append(
            ForeignKeySchema(
                id=len(foreign_keys),
                sequence=0,
                referenced_table=_name(target.this.name),
                from_column=column_name,
                to_column=_name(target.expressions[0].name),
                on_update="NO ACTION",
                on_delete="NO ACTION",
                match="NONE",
            )
        )

    type_names = {
        exp.DataType.Type.INT: "INTEGER",
        exp.DataType.Type.SMALLINT: "SMALLINT",
        exp.DataType.Type.BIGINT: "BIGINT",
        exp.DataType.Type.SERIAL: "INTEGER",
        exp.DataType.Type.BIGSERIAL: "BIGINT",
        exp.DataType.Type.SMALLSERIAL: "SMALLINT",
        exp.DataType.Type.FLOAT: "REAL",
        exp.DataType.Type.DOUBLE: "DOUBLE",
        exp.DataType.Type.TEXT: "TEXT",
        exp.DataType.Type.VARCHAR: "TEXT",
        exp.DataType.Type.UUID: "UUID",
        exp.DataType.Type.DECIMAL: "DECIMAL",
        exp.DataType.Type.BOOLEAN: "BOOLEAN",
        exp.DataType.Type.DATE: "DATE",
        exp.DataType.Type.TIMESTAMP: "TIMESTAMP",
        exp.DataType.Type.TIMESTAMPTZ: "TIMESTAMPTZ",
    }
    for definition in definitions:
        if isinstance(definition, exp.PrimaryKey):
            continue
        if isinstance(definition, exp.ForeignKey) and references:
            if len(definition.expressions) != 1 or not isinstance(
                definition.expressions[0], exp.Identifier
            ):
                raise SqlInputError("only single-column foreign keys are supported")
            ref = definition.args.get("reference")
            if not isinstance(ref, exp.Reference) or definition.args.get("options"):
                raise SqlInputError("unsupported foreign key")
            add_reference(_name(definition.expressions[0].name), ref)
            continue
        if isinstance(definition, exp.UniqueColumnConstraint) and references:
            unique = definition.this
            if (
                not isinstance(unique, exp.Schema)
                or len(unique.expressions) != 1
                or not isinstance(unique.expressions[0], exp.Identifier)
                or definition.args.get("options")
            ):
                raise SqlInputError("only single-column UNIQUE is supported")
            unique_columns.append((_name(unique.expressions[0].name),))
            continue
        if not isinstance(definition, exp.ColumnDef):
            raise SqlInputError("unsupported table-level constraint")
        column_name = _name(definition.name)
        if definition.kind is None or definition.kind.this not in type_names:
            raise SqlInputError("unsupported column type")
        parameters: list[int] = []
        for param in definition.kind.expressions:
            if (
                not isinstance(param, exp.DataTypeParam)
                or not isinstance(param.this, exp.Literal)
                or not param.this.is_int
            ):
                raise SqlInputError("unsupported type parameter")
            parameters.append(int(param.this.this))
        if parameters:
            if definition.kind.this == exp.DataType.Type.VARCHAR:
                valid_parameters = len(parameters) == 1 and 1 <= parameters[0] <= 10000
            elif definition.kind.this == exp.DataType.Type.DECIMAL:
                valid_parameters = (
                    len(parameters) in {1, 2}
                    and 1 <= parameters[0] <= 1000
                    and (len(parameters) == 1 or 0 <= parameters[1] <= parameters[0])
                )
            else:
                valid_parameters = False
            if not valid_parameters:
                raise SqlInputError("unsupported type parameters")
        kind = type_names[definition.kind.this]
        if not references and (
            kind not in {"INTEGER", "TEXT"}
            or definition.kind.this
            in {
                exp.DataType.Type.SERIAL,
                exp.DataType.Type.BIGSERIAL,
                exp.DataType.Type.SMALLSERIAL,
            }
        ):
            raise SqlInputError("only INTEGER and TEXT columns are supported")
        constraints = [type(item.kind).__name__ for item in definition.constraints]
        allowed = {"PrimaryKeyColumnConstraint", "NotNullColumnConstraint"}
        if references:
            allowed.update(
                {
                    "Reference",
                    "UniqueColumnConstraint",
                    "DefaultColumnConstraint",
                    "GeneratedAsIdentityColumnConstraint",
                }
            )
        if any(kind not in allowed for kind in constraints):
            raise SqlInputError("unsupported column constraint")
        primary = "PrimaryKeyColumnConstraint" in constraints or column_name == table_key
        if table_key and "PrimaryKeyColumnConstraint" in constraints:
            raise SqlInputError("multiple primary keys are unsupported")
        nullable = not primary and "NotNullColumnConstraint" not in constraints
        if not references and kind == "TEXT" and not nullable:
            raise SqlInputError("required TEXT columns are unsupported")
        default_sql = None
        for item in definition.constraints:
            if isinstance(item.kind, exp.Reference):
                add_reference(column_name, item.kind)
            elif isinstance(item.kind, exp.UniqueColumnConstraint):
                unique_columns.append((column_name,))
            elif isinstance(item.kind, exp.DefaultColumnConstraint):
                default = item.kind.this
                literal_negative = (
                    isinstance(default, exp.Neg)
                    and isinstance(default.this, exp.Literal)
                    and default.this.is_number
                )
                if (
                    not isinstance(default, (exp.Literal, exp.Boolean, exp.Null))
                    and not literal_negative
                ):
                    raise SqlInputError("only literal defaults are supported")
                default_sql = default.sql(dialect="postgres")
            elif isinstance(item.kind, exp.GeneratedAsIdentityColumnConstraint) and (
                item.kind.this is not False
                or any(value for key, value in item.kind.args.items() if key != "this")
            ):
                raise SqlInputError("only GENERATED BY DEFAULT AS IDENTITY is supported")
        columns.append(
            ColumnSchema(
                cid=len(columns),
                name=column_name,
                declared_type=kind,
                not_null=not nullable,
                default_sql=default_sql,
                primary_key_position=1 if primary else 0,
                hidden=0,
                type_parameters=tuple(parameters),
            )
        )
    if len({column.name for column in columns}) != len(columns):
        raise SqlInputError("duplicate column names")
    keys = [column for column in columns if column.primary_key_position]
    if len(keys) != 1 or keys[0].declared_type not in (KEY_TYPES if references else {"INTEGER"}):
        raise SqlInputError("exactly one supported single-column primary key is required")
    if any(key.from_column not in {column.name for column in columns} for key in foreign_keys):
        raise SqlInputError("foreign key references unknown local column")
    if any(
        column not in {item.name for item in columns}
        for group in unique_columns
        for column in group
    ):
        raise SqlInputError("UNIQUE references unknown column")
    return TableSchema(
        name=name,
        ddl=tree.sql(dialect="postgres"),
        columns=tuple(columns),
        foreign_keys=tuple(foreign_keys),
        unique_columns=tuple(unique_columns),
        index_ddls=(),
    )


def parse_postgres_database_schema(ddl: str) -> DatabaseSchema:
    """Parse supported related PostgreSQL tables into the shared schema."""
    try:
        statements = [tree for tree in sqlglot.parse(ddl, read="postgres") if tree]
    except ParseError as error:
        raise SqlInputError(f"SQL parse error: {error}") from error
    if not statements:
        raise SqlInputError("at least one CREATE TABLE is required")
    tables = tuple(_parse_table(tree, references=True) for tree in statements)
    if len({table.name for table in tables}) != len(tables):
        raise SqlInputError("duplicate table names")
    schema = DatabaseSchema(tables)
    for table in tables:
        for key in table.foreign_keys:
            try:
                parent = schema.table(key.referenced_table)
            except KeyError as error:
                raise SqlInputError("foreign key references unknown table") from error
            if not any(
                column.name == key.to_column and column.primary_key_position == 1
                for column in parent.columns
            ):
                raise SqlInputError("foreign key must reference a supported primary key")
            local = next(column for column in table.columns if column.name == key.from_column)
            target = next(column for column in parent.columns if column.name == key.to_column)
            if local.declared_type != target.declared_type:
                raise SqlInputError("foreign key type must match its primary key")
    _ordered_schema_tables(schema)
    return schema


def parse_query(sql: str, schema: Schema, *, allow_qualified: bool = False) -> exp.Query:
    """Validate the supported read-only SQL subset and schema references."""
    tree = _parse_one(sql)
    if not isinstance(tree, exp.Query) or (
        not allow_qualified and not isinstance(tree, exp.Select)
    ):
        raise SqlInputError("only SELECT is supported")
    unknown = sorted({type(node).__name__ for node in tree.walk()} - _ALLOWED_QUERY_NODES)
    if unknown:
        raise SqlInputError("unsupported query syntax: " + ", ".join(unknown))
    if allow_qualified:
        return _validate_query_scopes(tree, schema)
    tables = list(tree.find_all(exp.Table))
    known = {table.name: table for table in schema.database.tables}
    if len(list(tree.find_all(exp.Select))) != 1:
        raise SqlInputError("nested SELECT is unsupported")
    aliases: dict[str, TableSchema] = {}
    for table in tables:
        if table.name not in known or table.db or table.catalog:
            raise SqlInputError("only declared, unqualified tables are supported")
        alias = table.alias_or_name
        if alias in aliases:
            raise SqlInputError("duplicate table alias")
        aliases[alias] = known[table.name]
    for join in tree.find_all(exp.Join):
        if (
            not isinstance(join.this, exp.Table)
            or join.args.get("kind") not in (None, "INNER")
            or join.args.get("side") not in (None, "LEFT")
            or join.args.get("method")
            or join.args.get("using")
            or join.args.get("on") is None
        ):
            raise SqlInputError("only INNER and LEFT joins with ON are supported")
    output_aliases = {alias.alias for alias in tree.find_all(exp.Alias)}
    for column in tree.find_all(exp.Column):
        if column.table and not allow_qualified:
            raise SqlInputError(f"unsupported column reference: {column.sql()}")
        matching = [
            table for table in aliases.values() if column.name in {c.name for c in table.columns}
        ]
        if column.table:
            valid = column.table in aliases and column.name in {
                c.name for c in aliases[column.table].columns
            }
        else:
            valid = len(matching) == 1 or (not matching and column.name in output_aliases)
        if not valid:
            raise SqlInputError(f"unsupported column reference: {column.sql()}")
    for identifier in tree.find_all(exp.Identifier):
        _name(identifier.name)
    return tree


def _validate_query_scopes(tree: exp.Query, schema: Schema) -> exp.Query:
    """Check physical sources and column scopes without rewriting executed SQL."""
    for with_clause in tree.find_all(exp.With):
        if with_clause.args.get("recursive"):
            raise SqlInputError("recursive CTEs are unsupported")
    safe_casts = {
        exp.DataType.Type.INT,
        exp.DataType.Type.SMALLINT,
        exp.DataType.Type.BIGINT,
        exp.DataType.Type.FLOAT,
        exp.DataType.Type.DOUBLE,
        exp.DataType.Type.TEXT,
        exp.DataType.Type.DECIMAL,
        exp.DataType.Type.BOOLEAN,
        exp.DataType.Type.DATE,
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.UUID,
    }
    for cast in tree.find_all(exp.Cast):
        target = cast.args.get("to")
        if (
            not isinstance(target, exp.DataType)
            or target.this not in safe_casts
            or target.expressions
        ):
            raise SqlInputError("unsupported cast type")
    for join in tree.find_all(exp.Join):
        if (
            not isinstance(join.this, (exp.Table, exp.Subquery))
            or join.args.get("kind") not in (None, "INNER")
            or join.args.get("side") not in (None, "LEFT")
            or join.args.get("method")
            or join.args.get("using")
            or join.args.get("on") is None
        ):
            raise SqlInputError("only INNER and LEFT joins with ON are supported")
    tables = {table.name: table for table in schema.database.tables}
    try:
        for scope in traverse_scope(tree):
            for _, (_, source) in scope.selected_sources.items():
                if isinstance(source, exp.Table) and (
                    source.db or source.catalog or source.name not in tables
                ):
                    raise SqlInputError("only declared, unqualified tables are supported")
        mapping = {
            table.name: {column.name: column.declared_type for column in table.columns}
            for table in schema.database.tables
        }
        qualify(tree.copy(), schema=mapping, dialect="postgres", validate_qualify_columns=True)
    except OptimizeError as error:
        raise SqlInputError(f"invalid or ambiguous query reference: {error}") from error
    for identifier in tree.find_all(exp.Identifier):
        _name(identifier.name)
    return tree
