"""Warehouse queries: parse, resolve table names, and translate to DuckDB for the search.

The search runs on DuckDB (an emulation). A translation is exact or it is refused: SQLGlot's
"unsupported" warnings are errors here, and the divergences it passes silently are rewritten
(`WITH OFFSET`, `ARRAY_AGG ... IGNORE NULLS`, out-of-range array subscripts) or left to the
fidelity fixtures, which are the only thing that finds a silent divergence nobody listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, UnsupportedError
from sqlglot.optimizer.scope import traverse_scope

from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.warehouse_ddl import TableResolver

_PSEUDO = frozenset({"_table_suffix", "_partitiontime", "_partitiondate", "_file_name"})
_PROHIBITED = (
    exp.Alter,
    exp.Command,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Update,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


@dataclass
class Translation:
    sql: str
    notes: dict[str, int] = field(default_factory=dict)
    """How often each exact rewrite fired, and how many constructs were left uncertain."""


def parse_query(sql: str, dialect: Dialect) -> exp.Query:
    """One read-only query in the dialect, or `SqlInputError` naming what is wrong."""
    if not sql.strip():
        raise SqlInputError("SQL must not be empty")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect.read) if s]
    except ParseError as error:
        raise SqlInputError(f"SQL could not be parsed: {error}") from error
    if len(statements) != 1:
        raise SqlInputError("exactly one SQL statement is required")
    tree = statements[0]
    if not isinstance(tree, exp.Query) or isinstance(tree, exp.Values):
        raise SqlInputError("only a single read-only SELECT statement is supported")
    found = sorted({type(n).__name__ for n in tree.walk() if isinstance(n, _PROHIBITED)})
    if found:
        raise SqlInputError("statement contains unsupported operation(s): " + ", ".join(found))
    for function in tree.find_all(exp.Anonymous):
        if str(function.this).upper().startswith("ST_"):
            raise SqlInputError(f"unsupported construct: geography function {function.this}")
    return tree


def resolve_tables(tree: exp.Query, db: DatabaseSchema) -> exp.Query:
    """A copy whose physical tables are named by their collection, each keeping the alias the
    query could use (the last part of the name it was written with)."""
    resolver = TableResolver(db)
    out = tree.copy()
    tables: list[exp.Table] = []
    for scope in traverse_scope(out):
        for source in scope.sources.values():
            if isinstance(source, exp.Table) and not any(source is t for t in tables):
                tables.append(source)
    columns = {c.name for t in db.tables for c in t.columns}
    for table in tables:
        if "*" in table.name:
            raise SqlInputError(
                f"unsupported construct: wildcard table `{table.name}` "
                "(rewrite it as one table per shard family; see the warehouses page)"
            )
        written = table.name
        found = resolver.resolve(table)
        alias = table.alias
        table.set("this", exp.to_identifier(found.name))
        table.set("db", None)
        table.set("catalog", None)
        if not alias:
            table.set("alias", exp.TableAlias(this=exp.to_identifier(written)))
    defined = columns | {a.alias for a in out.find_all(exp.Alias)}
    for column in out.find_all(exp.Column):
        if column.name.lower() in _PSEUDO and column.name not in defined:
            raise SqlInputError(f"unsupported construct: pseudo column {column.name}")
    return out


def nested_references(tree: exp.Query, db: DatabaseSchema) -> set[tuple[str, str]]:
    """``(table, column)`` of every nested column the query reads, by dot access, `UNNEST` or a
    function on it. A reference that could be a column of more than one table counts for all."""
    nested = {
        (t.name, c.name)
        for t in db.tables
        for c in t.columns
        if c.type_tree is not None and c.type_tree.nested
    }
    if not nested:
        return set()
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        aliases[table.alias_or_name] = table.name
        aliases[table.name] = table.name
    found: set[tuple[str, str]] = set()
    for column in tree.find_all(exp.Column):
        parts = [
            p.name
            for p in (column.args.get("catalog"), column.args.get("db"), column.args.get("table"))
            if p is not None
        ] + [column.name]
        if parts[0] in aliases and len(parts) > 1:
            found.update({(aliases[parts[0]], parts[1])} & nested)
        for table_name, column_name in nested:
            if column_name == parts[0] and (len(parts) == 1 or parts[0] not in aliases):
                found.add((table_name, column_name))
    return found


# --- translation --------------------------------------------------------------------------------


def to_duckdb(tree: exp.Query, dialect: Dialect, db: DatabaseSchema) -> Translation:
    """DuckDB text for a resolved query; every rewrite is exact, every other gap is an error."""
    work = tree.copy()
    notes: dict[str, int] = {}
    if dialect.name == "bigquery":
        _array_agg_ignore_nulls(work, notes)
        _unnest_offset(work, db, notes)
        _bigquery_subscripts(work, notes)
        _guard_division(work, notes)
        _extract_dayofweek(work, notes)
        _date_trunc(work, dialect, db, notes)
    elif dialect.family == "presto":
        _presto_subscripts(work, db, notes)
        _truncate_integer_division(work, dialect, db, notes)
        _date_trunc(work, dialect, db, notes)
    _reject_array_agg_limit(work)
    try:
        text = work.sql(dialect="duckdb", unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as error:
        raise SqlInputError(f"unsupported construct: {error}") from error
    return Translation(text, notes)


def _bump(notes: dict[str, int], name: str) -> None:
    notes[name] = notes.get(name, 0) + 1


def _reject_array_agg_limit(tree: exp.Expression) -> None:
    for agg in tree.find_all(exp.ArrayAgg):
        if any(isinstance(n, exp.Limit) for n in agg.walk()):
            raise SqlInputError("unsupported construct: LIMIT inside ARRAY_AGG")


def _agg_value(agg: exp.ArrayAgg) -> exp.Expression:
    value: exp.Expression = agg.this
    if isinstance(value, exp.Order):
        value = value.this
    if isinstance(value, exp.Distinct):
        value = value.expressions[0]
    return value


def _array_agg_ignore_nulls(tree: exp.Expression, notes: dict[str, int]) -> None:
    """``ARRAY_AGG(x IGNORE NULLS ...)`` as ``ARRAY_AGG(x ...) FILTER (WHERE x IS NOT NULL)``."""
    for node in list(tree.find_all(exp.IgnoreNulls)):
        agg = node.this
        if not isinstance(agg, exp.ArrayAgg):
            continue
        if any(isinstance(n, exp.Limit) for n in agg.walk()):
            raise SqlInputError("unsupported construct: LIMIT inside ARRAY_AGG")
        value = _agg_value(agg).copy()
        keep = exp.Not(this=exp.Is(this=value, expression=exp.Null()))
        node.replace(exp.Filter(this=agg.copy(), expression=exp.Where(this=keep)))
        _bump(notes, "array_agg_ignore_nulls")


def _unnest_offset(tree: exp.Expression, db: DatabaseSchema, notes: dict[str, int]) -> None:
    """``UNNEST(a) AS e WITH OFFSET AS o``: DuckDB ordinality is 1-based, BigQuery offset 0-based.

    The ordinality column is renamed and every read of ``o`` in the enclosing query becomes
    ``(ordinal - 1) AS o``; the element and the offset get explicit column names, because SQLGlot
    otherwise drops the offset's name when the element has no alias.
    """
    columns = {c.name for t in db.tables for c in t.columns}
    for index, unnest in enumerate(list(tree.find_all(exp.Unnest))):
        offset = unnest.args.get("offset")
        if not offset:
            continue
        name = offset.name if isinstance(offset, exp.Expression) else str(offset)
        if name in columns:
            raise SqlInputError(
                f"unsupported construct: WITH OFFSET name {name!r} is also a column"
            )
        raw = f"__ord{index}"
        alias = unnest.args.get("alias")
        if alias is not None and alias.columns:
            element = alias.columns[0].name
        elif alias is not None and alias.name:
            element = alias.name
        else:
            element = f"__el{index}"
        unnest.set("alias", exp.TableAlias(this=exp.to_identifier(f"__u{index}")))
        unnest.set("offset", exp.to_identifier(raw))
        unnest.args["alias"].set("columns", [exp.to_identifier(element)])
        scope_root = unnest.find_ancestor(exp.Select) or tree
        for column in list(scope_root.find_all(exp.Column)):
            if column.name != name or column.table:
                continue
            replacement: exp.Expression = exp.Paren(
                this=exp.Sub(this=exp.column(raw), expression=exp.Literal.number(1))
            )
            if isinstance(column.parent, exp.Select) and column.arg_key == "expressions":
                replacement = exp.alias_(replacement, name)
            column.replace(replacement)
        _bump(notes, "unnest_with_offset")


def _guarded_subscript(
    array: exp.Expression, zero_based: exp.Expression, *, safe: bool
) -> exp.Expression:
    """``array[zero_based]``: NULL out of range if ``safe``, an error otherwise, as in BigQuery."""
    length = exp.Anonymous(this="len", expressions=[array.copy()])
    inside = exp.And(
        this=exp.GTE(this=zero_based.copy(), expression=exp.Literal.number(0)),
        expression=exp.LT(this=zero_based.copy(), expression=length),
    )
    picked = exp.Bracket(
        this=array.copy(),
        expressions=[exp.Add(this=zero_based.copy(), expression=exp.Literal.number(1))],
        offset=1,
    )
    if safe:
        return exp.Case(ifs=[exp.If(this=inside, true=picked)])  # NULL out of range
    outside = exp.Or(
        this=exp.LT(this=zero_based.copy(), expression=exp.Literal.number(0)),
        expression=exp.GTE(this=zero_based.copy(), expression=length.copy()),
    )
    failure = exp.Anonymous(
        this="error", expressions=[exp.Literal.string("array index out of bounds")]
    )
    return exp.Case(ifs=[exp.If(this=outside, true=failure)], default=picked)


def _bigquery_subscripts(tree: exp.Expression, notes: dict[str, int]) -> None:
    """BigQuery's ``arr[OFFSET(n)]`` is an error out of range; DuckDB gives NULL, and a negative
    index counts from the end. ``SAFE_*`` is NULL out of range, including negative."""
    for bracket in list(tree.find_all(exp.Bracket)):
        if len(bracket.expressions) != 1:
            continue
        index = bracket.expressions[0]
        if isinstance(index, exp.Literal) and index.is_string:
            raise SqlInputError("unsupported construct: JSON subscript")
        zero_based = (
            exp.Sub(this=index.copy(), expression=exp.Literal.number(1))
            if bracket.args.get("offset") == 1
            else index.copy()
        )
        safe = bool(bracket.args.get("safe"))
        bracket.replace(_guarded_subscript(bracket.this, zero_based, safe=safe))
        _bump(notes, "safe_subscript" if safe else "checked_subscript")


def _guard_division(tree: exp.Expression, notes: dict[str, int]) -> None:
    """BigQuery raises an error on division by zero (``/``, ``DIV``, ``MOD``); DuckDB gives
    infinity or NULL. ``SAFE_DIVIDE`` is a different node and keeps its NULL."""
    for node in list(tree.find_all(exp.Div, exp.IntDiv, exp.Mod)):
        divisor = node.expression
        if isinstance(divisor, exp.Literal) and divisor.is_number and float(divisor.name) != 0:
            continue
        failure = exp.Anonymous(this="error", expressions=[exp.Literal.string("division by zero")])
        zero = exp.EQ(this=divisor.copy(), expression=exp.Literal.number(0))
        node.replace(exp.Case(ifs=[exp.If(this=zero, true=failure)], default=node.copy()))
        _bump(notes, "checked_division")


def _extract_dayofweek(tree: exp.Expression, notes: dict[str, int]) -> None:
    """BigQuery's DAYOFWEEK is 1 to 7 from Sunday; DuckDB's is 0 to 6 from Sunday."""
    for node in list(tree.find_all(exp.Extract)):
        unit = node.this.name.upper() if isinstance(node.this, exp.Expression) else ""
        if unit == "DAYOFWEEK":
            shifted = exp.Add(this=node.copy(), expression=exp.Literal.number(1))
            node.replace(exp.Paren(this=shifted))
            _bump(notes, "dayofweek_shift")
        elif unit == "WEEK":
            raise SqlInputError("unsupported construct: EXTRACT(WEEK ...), a Sunday-based number")


def _typed_copy(tree: exp.Expression, db: DatabaseSchema, read: str) -> exp.Expression | None:
    from sqlglot.optimizer.annotate_types import annotate_types
    from sqlglot.optimizer.qualify import qualify

    schema = {
        t.name: {
            c.name: c.declared_type
            for c in t.columns
            if c.type_tree is not None and not c.type_tree.nested
        }
        for t in db.tables
    }
    try:
        typed = qualify(
            tree.copy(), schema=schema, dialect=read, validate_qualify_columns=False, identify=False
        )
        return annotate_types(typed, schema=schema, dialect=read)
    except Exception:
        return None


_TRUNC_PARTS = {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR", "HOUR", "MINUTE", "SECOND"}


def _date_trunc(
    tree: exp.Expression, dialect: Dialect, db: DatabaseSchema, notes: dict[str, int]
) -> None:
    """``DATE_TRUNC`` of a date is a DATE in BigQuery and Presto and a TIMESTAMP in DuckDB. A
    BigQuery WEEK begins on Sunday where DuckDB's (and Presto's) begins on Monday."""
    nodes = list(tree.find_all(exp.DateTrunc, exp.TimestampTrunc))
    if not nodes:
        return
    typed = _typed_copy(tree, db, dialect.read)
    seen_nodes = list(typed.find_all(exp.DateTrunc, exp.TimestampTrunc)) if typed else []
    unknown = "unsupported construct: DATE_TRUNC on an expression of unknown type"
    if len(seen_nodes) != len(nodes):
        raise SqlInputError(unknown)
    for node, seen in zip(nodes, seen_nodes, strict=True):
        unit = node.args.get("unit")
        part = unit.name.upper() if isinstance(unit, exp.Expression) else str(unit).upper()
        if part not in _TRUNC_PARTS:
            raise SqlInputError(f"unsupported construct: DATE_TRUNC part {part}")
        argument = seen.this
        is_date = argument.is_type(exp.DataType.Type.DATE)
        if not is_date and not argument.is_type(
            exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ, exp.DataType.Type.DATETIME
        ):
            raise SqlInputError(unknown)
        day = sqlglot.parse_one("INTERVAL 1 DAY", read="duckdb")
        sunday_week = part == "WEEK" and dialect.name == "bigquery"
        subject = node.this.copy()
        if sunday_week:
            subject = exp.Add(this=subject, expression=day.copy())
        replacement: exp.Expression = exp.Anonymous(
            this="date_trunc", expressions=[exp.Literal.string(part.lower()), subject]
        )
        if sunday_week:
            replacement = exp.Sub(this=replacement, expression=day.copy())
        if is_date:
            replacement = exp.Cast(this=replacement, to=exp.DataType.build("DATE"))
        node.replace(replacement)
        _bump(notes, "date_trunc")


def _columns_of_kind(db: DatabaseSchema, kind: str) -> set[str]:
    return {
        c.name
        for t in db.tables
        for c in t.columns
        if c.type_tree is not None and c.type_tree.kind == kind
    }


def _presto_subscripts(tree: exp.Expression, db: DatabaseSchema, notes: dict[str, int]) -> None:
    """Presto's ``arr[n]`` is an error out of range and ``m[k]`` an error for a missing key;
    DuckDB gives NULL for both. ``element_at`` is NULL in Presto too and is left alone. Only
    subscripts on a column known to be an array or a map are rewritten; others are counted as
    uncertain. SQLGlot hands subscripts over 0-based, except ``element_at``, which it flags."""
    arrays, maps = _columns_of_kind(db, "ARRAY"), _columns_of_kind(db, "MAP")
    for bracket in list(tree.find_all(exp.Bracket)):
        if len(bracket.expressions) != 1 or bracket.args.get("safe"):
            continue
        target, index = bracket.this, bracket.expressions[0]
        name = target.name if isinstance(target, exp.Column) else None
        if name in arrays:
            bracket.replace(_guarded_subscript(target, index, safe=False))
            _bump(notes, "checked_subscript")
        elif name in maps:
            bracket.replace(_checked_map_subscript(target, index))
            _bump(notes, "checked_map_subscript")
        else:
            _bump(notes, "subscript_uncertain")


def _checked_map_subscript(target: exp.Expression, key: exp.Expression) -> exp.Expression:
    missing = exp.Anonymous(this="error", expressions=[exp.Literal.string("key not present")])
    present = exp.Anonymous(this="map_contains", expressions=[target.copy(), key.copy()])
    picked = exp.Bracket(this=target.copy(), expressions=[key.copy()], offset=1)
    null_map = exp.If(this=exp.Is(this=target.copy(), expression=exp.Null()), true=exp.Null())
    return exp.Case(ifs=[null_map, exp.If(this=present, true=picked)], default=missing)


def _truncate_integer_division(
    tree: exp.Expression, dialect: Dialect, db: DatabaseSchema, notes: dict[str, int]
) -> None:
    from isitright.packs.sql.dialect_fidelity import truncate_integer_divisions

    schema = {
        t.name: {
            c.name: c.declared_type
            for c in t.columns
            if c.type_tree is not None and not c.type_tree.nested
        }
        for t in db.tables
    }
    translated, uncertain = truncate_integer_divisions(tree, schema, dialect.read)
    if translated:
        notes["integer_division"] = translated
    if uncertain:
        notes["division_uncertain"] = uncertain
