"""Warehouse DDL import: BigQuery, Presto/Trino and Hive `CREATE TABLE` statements.

Reads the forms people can get without moving data (`INFORMATION_SCHEMA.TABLES.ddl`, Spider's
`DDL.csv`, `SHOW CREATE TABLE`, Hive DDL) into the shared schema. Keys are optional; keys a
warehouse declares but does not enforce are kept as declared. Partition columns are ordinary
columns. A table is named by the last part of its qualified name (``dataset_table`` if two tables
share it), and `TableResolver` maps the names queries use back to tables.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.schema import ColumnSchema, DatabaseSchema, ForeignKeySchema, TableSchema
from isitright.packs.sql.typetree import TypeNode, duckdb_type, from_sqlglot

NOT_ENFORCED = "NOT ENFORCED"


def parse_warehouse_schema(ddl: str, dialect: Dialect) -> DatabaseSchema:
    """The schema of every `CREATE TABLE` in ``ddl``, read in the given warehouse dialect."""
    statements = _parse(ddl, dialect)
    if not statements:
        raise SqlInputError("at least one CREATE TABLE is required")
    pending = [_table(tree, dialect) for tree in statements]
    names: dict[str, int] = {}
    for table in pending:
        names[table.name] = names.get(table.name, 0) + 1
    tables: list[TableSchema] = []
    for table in pending:
        if names[table.name] > 1:
            parts = (table.qualified or table.name).split(".")
            unique_name = "_".join(parts[-2:])
            table = _renamed(table, unique_name)
        tables.append(table)
    if len({t.name for t in tables}) != len(tables):
        raise SqlInputError("duplicate table names after qualification")
    return _link_foreign_keys(DatabaseSchema(tuple(tables)))


def _parse(ddl: str, dialect: Dialect) -> list[exp.Expression]:
    readers = [dialect.read] + (["hive"] if dialect.family == "presto" else [])
    last: Exception | None = None
    for reader in readers:
        try:
            parsed = [s for s in sqlglot.parse(ddl, read=reader) if s]
        except ParseError as error:
            last = error
            continue
        if all(isinstance(s, exp.Create) for s in parsed):
            return parsed
        other = next(s for s in parsed if not isinstance(s, exp.Create))
        raise SqlInputError(f"only CREATE TABLE is supported, not {type(other).__name__}")
    raise SqlInputError(f"DDL could not be parsed: {last}")


def _renamed(table: TableSchema, name: str) -> TableSchema:
    from dataclasses import replace

    return replace(table, name=name)


def _table(tree: exp.Expression, dialect: Dialect) -> TableSchema:
    assert isinstance(tree, exp.Create)
    kind = tree.args.get("kind")
    if kind != "TABLE":
        raise SqlInputError(f"unsupported DDL: CREATE {kind or 'statement'} (only tables)")
    if tree.args.get("expression") is not None:
        raise SqlInputError("unsupported DDL: CREATE TABLE ... AS")
    schema = tree.this
    if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
        raise SqlInputError("expected explicit table columns")
    table = schema.this
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    qualified = ".".join(parts)
    columns: list[ColumnSchema] = []
    declared: list[tuple[str, ...]] = []
    foreign: list[tuple[str, str, str | None]] = []
    for item in schema.expressions:
        if isinstance(item, exp.ColumnDef):
            columns.append(_column(item, len(columns)))
        elif isinstance(item, exp.PrimaryKey):
            declared.append(tuple(_identifiers(item.expressions)))
        elif isinstance(item, exp.ForeignKey):
            local = _identifiers(item.expressions)
            reference = item.args.get("reference")
            if len(local) != 1 or not isinstance(reference, exp.Reference):
                continue  # a composite foreign key is not imported; the constraints file may add it
            target = reference.this
            if isinstance(target, exp.Schema) and isinstance(target.this, exp.Table):
                names = _identifiers(target.expressions)
                foreign.append((local[0], _qualified(target.this), names[0] if names else None))
        elif isinstance(
            item, exp.Constraint | exp.UniqueColumnConstraint | exp.CheckColumnConstraint
        ):
            continue  # not enforced by warehouses; nothing to import
        else:
            raise SqlInputError(f"unsupported table element: {type(item).__name__}")
    properties = tree.args.get("properties")
    props = list(properties.expressions) if properties else []
    partitions = _partitions(props, columns, dialect)
    columns.extend(c for c in partitions[1] if c.name not in {x.name for x in columns})
    description = _table_description(props)
    column_names = {c.name for c in columns}
    if len(column_names) != len(columns):
        raise SqlInputError("duplicate column names")
    for key in declared:
        if any(c not in column_names for c in key):
            raise SqlInputError("PRIMARY KEY names an unknown column")
    columns = _with_keys(columns, declared)
    unique = tuple(k for k in declared if len(k) > 1)
    table_schema = TableSchema(
        name=table.name,
        ddl=tree.sql(dialect=dialect.read),
        columns=tuple(columns),
        foreign_keys=tuple(
            ForeignKeySchema(
                id=i,
                sequence=0,
                referenced_table=target,
                from_column=local,
                to_column=to,
                on_update=NOT_ENFORCED,
                on_delete=NOT_ENFORCED,
                match="NONE",
            )
            for i, (local, target, to) in enumerate(foreign)
            if local in column_names
        ),
        unique_columns=unique,
        index_ddls=(),
        qualified=qualified,
        partition_columns=tuple(partitions[0]),
        declared_keys=tuple(declared),
        description=description,
    )
    return _with_engine_ddl(table_schema)


def _identifiers(items: list[exp.Expression]) -> list[str]:
    out = []
    for item in items:
        if isinstance(item, exp.Identifier | exp.Column):
            out.append(item.name)
        elif isinstance(item, exp.Ordered) and isinstance(item.this, exp.Column):
            out.append(item.this.name)
        else:
            raise SqlInputError(f"unsupported key element: {item.sql()}")
    return out


def _qualified(table: exp.Table) -> str:
    return ".".join(p for p in (table.catalog, table.db, table.name) if p)


def _column(definition: exp.ColumnDef, position: int) -> ColumnSchema:
    constraints = [c.kind for c in definition.constraints]
    tree = from_sqlglot(definition.args.get("kind"))
    not_null = any(isinstance(c, exp.NotNullColumnConstraint) for c in constraints)
    primary = any(isinstance(c, exp.PrimaryKeyColumnConstraint) for c in constraints)
    description = None
    for constraint in constraints:
        if isinstance(constraint, exp.CommentColumnConstraint):
            description = constraint.this.name if constraint.this is not None else None
        elif isinstance(constraint, exp.Properties):
            for prop in constraint.expressions:
                if isinstance(prop, exp.Property) and prop.name.lower() == "description":
                    description = prop.args["value"].name
    return ColumnSchema(
        cid=position,
        name=definition.name,
        declared_type=tree.kind,
        not_null=not_null or primary,
        default_sql=None,
        primary_key_position=1 if primary else 0,
        hidden=0,
        type_tree=tree,
        description=description or None,
    )


def _partitions(
    props: list[exp.Expression], columns: list[ColumnSchema], dialect: Dialect
) -> tuple[list[str], list[ColumnSchema]]:
    """Partition column names, and columns Hive's ``PARTITIONED BY`` adds after the others."""
    names: list[str] = []
    extra: list[ColumnSchema] = []
    for prop in props:
        if not isinstance(prop, exp.PartitionedByProperty):
            continue
        value = prop.this
        if isinstance(value, exp.Schema):  # Hive: PARTITIONED BY (ds STRING)
            for item in value.expressions:
                if isinstance(item, exp.ColumnDef):
                    extra.append(_column(item, len(columns) + len(extra)))
                    names.append(item.name)
                elif isinstance(item, exp.Identifier | exp.Column):
                    names.append(item.name)
        elif isinstance(value, exp.Array):  # Presto: partitioned_by = ARRAY['ds']
            names.extend(e.name for e in value.expressions if isinstance(e, exp.Literal))
        else:  # BigQuery: PARTITION BY DATE(ts) / ts / _PARTITIONDATE
            names.extend(c.name for c in value.find_all(exp.Column))
    known = {c.name for c in columns} | {c.name for c in extra}
    return [n for n in names if n in known], extra


def _table_description(props: list[exp.Expression]) -> str | None:
    for prop in props:
        if isinstance(prop, exp.SchemaCommentProperty):
            return str(prop.this.name)
        if isinstance(prop, exp.Property) and prop.name.lower() == "description":
            return str(prop.args["value"].name)
    return None


def _with_keys(columns: list[ColumnSchema], declared: list[tuple[str, ...]]) -> list[ColumnSchema]:
    from dataclasses import replace

    single = [k[0] for k in declared if len(k) == 1]
    if len(single) > 1:
        single = single[:1]
    return [
        replace(c, primary_key_position=1, not_null=True) if c.name in single else c
        for c in columns
    ]


def _with_engine_ddl(table: TableSchema) -> TableSchema:
    from dataclasses import replace

    body = ", ".join(
        f'"{c.name}" {duckdb_type(_tree(c))}{" NOT NULL" if c.not_null else ""}'
        for c in table.columns
    )
    return replace(table, engine_ddl=f'CREATE TABLE "{table.name}" ({body})')


def _tree(column: ColumnSchema) -> TypeNode:
    assert column.type_tree is not None
    return column.type_tree


def _link_foreign_keys(schema: DatabaseSchema) -> DatabaseSchema:
    """Point each declared foreign key at a table by name; drop ones whose table is not imported."""
    from dataclasses import replace

    resolver = TableResolver(schema)
    tables = []
    for table in schema.tables:
        keys = []
        for key in table.foreign_keys:
            target = resolver.find(key.referenced_table)
            if target is not None:
                keys.append(replace(key, referenced_table=target.name))
        tables.append(replace(table, foreign_keys=tuple(keys)))
    return DatabaseSchema(tuple(tables))


class TableResolver:
    """Maps a table reference in a query to a table: the reference's parts must end the name."""

    def __init__(self, schema: DatabaseSchema) -> None:
        self.schema = schema

    def find(self, reference: str) -> TableSchema | None:
        wanted = _split(reference)
        matches = [
            t for t in self.schema.tables if _ends_with(_split(t.qualified or t.name), wanted)
        ]
        if not matches:
            matches = [t for t in self.schema.tables if t.name == reference]
        if len(matches) > 1:
            names = ", ".join(sorted(t.qualified or t.name for t in matches))
            raise SqlInputError(f"table reference {reference!r} is ambiguous: {names}")
        return matches[0] if matches else None

    def resolve(self, table: exp.Table) -> TableSchema:
        found = self.find(_qualified(table))
        if found is None:
            raise SqlInputError(f"table {_qualified(table)!r} is not in the schema")
        return found


_QUOTED = re.compile(r"`([^`]*)`")


def _split(name: str) -> list[str]:
    return [p for p in name.replace("`", "").split(".") if p]


def _ends_with(full: list[str], tail: list[str]) -> bool:
    return len(tail) <= len(full) and full[len(full) - len(tail) :] == tail
