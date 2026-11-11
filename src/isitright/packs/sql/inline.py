"""Confirmation text: a query with every table replaced by inline literal rows.

A native warehouse host runs only text whose tables are inline: every table reference becomes a
subquery of typed literal rows (BigQuery: ``UNNEST`` of an array of structs; Presto/Trino:
``VALUES`` with casts), so no real table is read, no production row is mixed into the small world,
and nothing is scanned. `assert_inline_only` is the guard the hosts call on the final text, by
parsing it again: a reference the rewrite missed makes it raise before anything is sent.
"""

from __future__ import annotations

import base64
from decimal import Decimal
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope

from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.schema import ColumnSchema, DatabaseSchema, TableSchema
from isitright.packs.sql.state import DatabaseState, TableState
from isitright.packs.sql.typetree import (
    INTEGERS,
    TypeNode,
    bigquery_type,
    presto_type,
)


class RealTableReference(SqlInputError):
    """The final SQL still names a table that is not an inline one."""


_FORBIDDEN = (
    exp.Alter,
    exp.Command,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Update,
    exp.Use,
)


def assert_inline_only(sql: str, dialect: Dialect) -> None:
    """Raise `RealTableReference` unless every table in ``sql`` is inline or a CTE of the query."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect.read) if s]
    except ParseError as error:
        raise RealTableReference(f"the text to send could not be parsed: {error}") from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise RealTableReference("the text to send is not one query")
    tree = statements[0]
    if any(isinstance(node, _FORBIDDEN) for node in tree.walk()):
        raise RealTableReference("the text to send contains a statement other than a query")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                raise RealTableReference(f"the text to send still reads table {source.sql()!r}")
    for table in tree.find_all(exp.Table):
        if table.name not in ctes:
            raise RealTableReference(f"the text to send still reads table {table.sql()!r}")


# --- literals ---------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value)


def _bq_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def _pr_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bytes_of(value: Any) -> bytes:
    return value if isinstance(value, bytes) else base64.b64decode(value["$bytes"])


def bigquery_literal(node: TypeNode, value: Any) -> str:
    """A typed BigQuery literal for a state value (JSON form, or the python value of a scalar)."""
    typed = bigquery_type(node)
    if value is None:
        return f"CAST(NULL AS {typed})"
    if node.kind == "ARRAY" and node.element is not None:
        if not value:
            return f"ARRAY<{bigquery_type(node.element)}>[]"
        return "[" + ", ".join(bigquery_literal(node.element, v) for v in value) + "]"
    if node.kind == "STRUCT":
        inner = ", ".join(bigquery_literal(t, value.get(n)) for n, t, _ in node.fields)
        return f"{typed}({inner})"
    if node.kind == "MAP":
        raise SqlInputError("unsupported column type: MAP in BigQuery")
    if node.kind == "BYTES":
        return f"FROM_BASE64('{base64.b64encode(_bytes_of(value)).decode('ascii')}')"
    if node.kind == "BOOLEAN":
        return "TRUE" if value else "FALSE"
    if node.kind in INTEGERS:
        return f"CAST({int(value)} AS INT64)"
    if node.kind in ("REAL", "DOUBLE"):
        return f"CAST({_bq_string(repr(float(value)))} AS FLOAT64)"
    if node.kind == "DECIMAL":
        return f"CAST({_bq_string(_text(Decimal(str(value))))} AS {typed})"
    if node.kind == "DATE":
        return f"DATE {_bq_string(_text(value))}"
    if node.kind == "TIME":
        return f"TIME {_bq_string(_text(value))}"
    if node.kind == "TIMESTAMP":
        return f"DATETIME {_bq_string(_text(value))}"
    if node.kind == "TIMESTAMPTZ":
        return f"TIMESTAMP {_bq_string(_text(value))}"
    return _bq_string(_text(value))


def presto_literal(node: TypeNode, value: Any) -> str:
    typed = presto_type(node)
    if value is None:
        return f"CAST(NULL AS {typed})"
    if node.kind == "ARRAY" and node.element is not None:
        items = ", ".join(presto_literal(node.element, v) for v in value)
        return f"CAST(ARRAY[{items}] AS {typed})"
    if node.kind == "STRUCT":
        inner = ", ".join(presto_literal(t, value.get(n)) for n, t, _ in node.fields)
        return f"CAST(ROW({inner}) AS {typed})"
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        keys = ", ".join(presto_literal(node.key, k) for k, _ in value)
        values = ", ".join(presto_literal(node.value, v) for _, v in value)
        return f"CAST(MAP(ARRAY[{keys}], ARRAY[{values}]) AS {typed})"
    if node.kind == "BYTES":
        return f"from_base64('{base64.b64encode(_bytes_of(value)).decode('ascii')}')"
    if node.kind == "BOOLEAN":
        return "TRUE" if value else "FALSE"
    if node.kind in INTEGERS:
        return f"CAST({int(value)} AS {typed})"
    if node.kind in ("REAL", "DOUBLE"):
        return f"CAST({float(value)!r} AS {typed})"
    if node.kind == "DECIMAL":
        return f"CAST({_pr_string(_text(Decimal(str(value))))} AS {typed})"
    if node.kind == "DATE":
        return f"DATE {_pr_string(_text(value))}"
    if node.kind == "TIME":
        return f"TIME {_pr_string(_text(value))}"
    if node.kind == "TIMESTAMP":
        return f"CAST({_pr_string(_text(value))} AS TIMESTAMP)"
    if node.kind == "TIMESTAMPTZ":
        return f"CAST({_pr_string(_text(value))} AS {typed})"
    return _pr_string(_text(value))


# --- inline tables ------------------------------------------------------------------------------


def _tree(column: ColumnSchema) -> TypeNode:
    assert column.type_tree is not None
    return column.type_tree


def _quote(name: str, dialect: Dialect) -> str:
    return f"`{name}`" if dialect.name == "bigquery" else '"' + name.replace('"', '""') + '"'


def inline_table(table: TableSchema, rows: TableState, dialect: Dialect) -> str:
    """The inline subquery that stands for a table: typed rows, an empty table typed as well."""
    columns = [c for c in table.columns if c.hidden == 0]
    names = [_quote(c.name, dialect) for c in columns]
    if dialect.name == "bigquery":
        struct = (
            "STRUCT<"
            + ", ".join(
                f"{n} {bigquery_type(_tree(c))}" for n, c in zip(names, columns, strict=True)
            )
            + ">"
        )
        if not rows.rows:
            return f"(SELECT * FROM UNNEST(ARRAY<{struct}>[]))"
        items = ", ".join(
            f"{struct}("
            + ", ".join(bigquery_literal(_tree(c), v) for c, v in zip(columns, row, strict=True))
            + ")"
            for row in rows.rows
        )
        return f"(SELECT * FROM UNNEST([{items}]))"
    header = ", ".join(names)
    if not rows.rows:
        nulls = ", ".join(f"CAST(NULL AS {presto_type(_tree(c))})" for c in columns)
        return f"(SELECT * FROM (VALUES ({nulls})) AS v({header}) WHERE FALSE)"
    values = ", ".join(
        "("
        + ", ".join(presto_literal(_tree(c), v) for c, v in zip(columns, row, strict=True))
        + ")"
        for row in rows.rows
    )
    return f"(SELECT * FROM (VALUES {values}) AS v({header}))"


def inline_sql(tree: exp.Query, dialect: Dialect, db: DatabaseSchema, state: DatabaseState) -> str:
    """The query (resolved to collection names) with each table replaced by its inline rows.

    Tables are first renamed to placeholders in the tree and the inline text is spliced in after
    the query is generated, so the literals reach the engine exactly as `inline_table` wrote them.
    """
    by_name = {t.name: t for t in state.tables}
    work = tree.copy()
    pieces: dict[str, str] = {}
    tables: list[tuple[exp.Table, Any]] = []
    for scope in traverse_scope(work):
        for source in scope.sources.values():
            if isinstance(source, exp.Table) and not any(source is seen for seen, _ in tables):
                tables.append((source, scope))
    for source, scope in tables:
        table = db.table(source.name)
        rows = by_name.get(table.name) or TableState(table.name, (), ())
        alias = source.alias or source.name
        if alias.lower() == source.name.lower() and alias.lower() in {
            c.name.lower() for c in table.columns
        }:
            # A table named like one of its columns: as a subquery alias the name would also be a
            # row-valued range variable, and BigQuery then reads the bare column name as the whole
            # row (seen on bq025). Use another alias and move the qualified references to it.
            alias = f"{source.name}__t"
            for column in scope.columns:
                if column.table and column.table.lower() == source.name.lower():
                    column.set("table", exp.to_identifier(alias))
        placeholder = f"__inline_{len(pieces)}__"
        pieces[placeholder] = inline_table(table, rows, dialect)
        source.set("this", exp.to_identifier(placeholder))
        source.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
    text = work.sql(dialect=dialect.read)
    for placeholder, inline in pieces.items():
        for spelled in (f"`{placeholder}`", f'"{placeholder}"', placeholder):
            text = text.replace(spelled, inline)
    return text
