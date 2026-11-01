"""Query-guidance extraction and SQLite read-only query validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class SqlValidationError(ValueError):
    """Raised when SQL is malformed or outside the supported read-only subset."""


@dataclass(frozen=True, slots=True)
class SqlStatement:
    """A validated single SELECT statement and its comparison-relevant traits."""

    expression: exp.Query
    top_level_ordered: bool


@dataclass(frozen=True, slots=True)
class QueryGuidance:
    """Cheap search guidance harvested without attempting an AST diff."""

    tables: frozenset[str]
    columns: frozenset[tuple[str | None, str]]
    literals: tuple[Any, ...]
    has_distinct: bool
    has_join: bool
    has_filter: bool
    has_aggregate: bool
    bound_literals: tuple[tuple[str | None, str, Any], ...] = ()
    """``(table, column, literal)`` where the query compares the column (or an expression over it)
    with the literal. A literal that is only an argument, such as the format of ``STRFTIME``, is not
    bound to any column."""

    def references_column(self, table: str, column: str) -> bool:
        """Include unqualified references conservatively for each matching table."""
        return (table, column) in self.columns or (None, column) in self.columns


_COMPARISONS = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Like,
    exp.ILike,
    exp.Glob,
    exp.NullSafeEQ,
    exp.NullSafeNEQ,
)


def _literal_value(literal: exp.Literal) -> Any:
    sign = -1 if isinstance(literal.parent, exp.Neg) else 1
    if literal.is_int:
        return sign * int(literal.this)
    if literal.is_number:
        return sign * float(literal.this)
    if literal.is_string:
        return str(literal.this)
    return None


def _comparison_sides(node: exp.Expression) -> tuple[list[exp.Expression], list[exp.Expression]]:
    if isinstance(node, _COMPARISONS):
        return [node.this], [node.args["expression"]]
    if isinstance(node, exp.In):
        return [node.this], list(node.expressions)
    if isinstance(node, exp.Between):
        return [node.this], [node.args["low"], node.args["high"]]
    return [], []


def _bind_literals(
    statement: SqlStatement, aliases: dict[str, str]
) -> list[tuple[str | None, str, Any]]:
    """Pair each column with the literals it is compared against, in either direction."""
    bound: list[tuple[str | None, str, Any]] = []
    for node in statement.expression.walk():
        left, right = _comparison_sides(node)
        for these, others in ((left, right), (right, left)):
            columns = [c for e in these for c in e.find_all(exp.Column)]
            literals = [
                value
                for e in others
                for lit in e.find_all(exp.Literal)
                if (value := _literal_value(lit)) is not None
            ]
            for column in columns:
                qualifier = column.table or None
                resolved = aliases.get(qualifier, qualifier) if qualifier else None
                bound.extend((resolved, column.name, value) for value in literals)
    return bound


def harvest_query_guidance(*statements: SqlStatement) -> QueryGuidance:
    """Collect references and literals from already-validated SQLGlot queries.

    Validation and dialect-specific interpretation remain the engine's responsibility.
    """
    tables: set[str] = set()
    columns: set[tuple[str | None, str]] = set()
    literals: list[Any] = []
    bound: list[tuple[str | None, str, Any]] = []
    has_distinct = False
    has_join = False
    has_filter = False
    has_aggregate = False
    for statement in statements:
        aliases: dict[str, str] = {}
        for table in statement.expression.find_all(exp.Table):
            name = table.name
            tables.add(name)
            aliases[table.alias_or_name] = name
        for column in statement.expression.find_all(exp.Column):
            qualifier = column.table or None
            resolved_qualifier = aliases.get(qualifier, qualifier) if qualifier else None
            columns.add((resolved_qualifier, column.name))
        for literal in statement.expression.find_all(exp.Literal):
            if (value := _literal_value(literal)) is not None:
                literals.append(value)
        bound.extend(_bind_literals(statement, aliases))
        has_distinct = has_distinct or any(
            select.args.get("distinct") is not None
            for select in statement.expression.find_all(exp.Select)
        )
        has_join = has_join or any(statement.expression.find_all(exp.Join))
        has_filter = has_filter or any(statement.expression.find_all(exp.Where))
        has_aggregate = has_aggregate or any(
            isinstance(node, exp.AggFunc) for node in statement.expression.walk()
        )
    return QueryGuidance(
        tables=frozenset(tables),
        columns=frozenset(columns),
        literals=tuple(dict.fromkeys(literals)),
        has_distinct=has_distinct,
        has_join=has_join,
        has_filter=has_filter,
        has_aggregate=has_aggregate,
        bound_literals=tuple(dict.fromkeys(bound)),
    )


def validate_read_only_query(sql: str) -> SqlStatement:
    """Return a parsed query after enforcing the SQL safety contract."""
    if not sql.strip():
        raise SqlValidationError("SQL must not be empty")

    try:
        statements = [statement for statement in sqlglot.parse(sql, read="sqlite") if statement]
    except ParseError as error:
        raise SqlValidationError(f"SQL could not be parsed: {error}") from error

    if len(statements) != 1:
        raise SqlValidationError("exactly one SQL statement is required")

    statement = statements[0]
    if not isinstance(statement, exp.Query) or isinstance(statement, exp.Values):
        raise SqlValidationError("only a single read-only SELECT statement is supported")

    prohibited = {
        "Alter",
        "Attach",
        "Command",
        "Commit",
        "Create",
        "Delete",
        "Detach",
        "Drop",
        "Insert",
        "Merge",
        "Pragma",
        "Rollback",
        "Transaction",
        "Update",
        "Use",
    }
    found = sorted({type(node).__name__ for node in statement.walk()} & prohibited)
    if found:
        raise SqlValidationError("statement contains unsupported operation(s): " + ", ".join(found))

    return SqlStatement(
        expression=statement,
        top_level_ordered=statement.args.get("order") is not None,
    )
