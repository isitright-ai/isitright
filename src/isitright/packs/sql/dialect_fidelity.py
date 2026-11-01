"""Where DuckDB is not PostgreSQL, and what the translation does about it.

DuckDB runs PostgreSQL programs as a labeled emulation. A divergence found there is a candidate,
re-executed natively when a PostgreSQL instance is available. The translation removes the
differences it can detect, and reports the ones it cannot.

Integer division: PostgreSQL divides two integers with truncation (``5 / 2`` is 2); DuckDB's ``/``
is always floating point (2.5). SQLGlot leaves the operator unchanged. Here every ``/`` whose
operands are both integers, by the declared column types and literals of the query, becomes DuckDB's
truncating ``//``, guarded so that a zero divisor is an error as in PostgreSQL (DuckDB's ``//``
gives NULL). A division whose operand types cannot be determined stays as written and is
counted as uncertain, so a finding that depends on it is left to native verification.

Known remaining differences (not translated; native verification is what catches them):
``numeric / integer`` is exact decimal division in PostgreSQL and floating point in DuckDB, and
floating-point division by zero is an error in PostgreSQL and infinity in DuckDB (the engine
reports a non-finite result as inconclusive).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify

from isitright.packs.sql.schema import DatabaseSchema

Catalog = tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class Translation:
    sql: str
    integer_divisions_translated: int = 0
    divisions_uncertain: int = 0


def catalog_of(db: DatabaseSchema) -> Catalog:
    """Table and column types as a hashable value, for the translation cache."""
    return tuple(
        (t.name, tuple((c.name, c.declared_type.upper()) for c in t.columns)) for t in db.tables
    )


def _truncating(division: exp.Div) -> exp.Expression:
    """DuckDB's ``//``, guarded so that a zero divisor is an error as in PostgreSQL (DuckDB gives
    NULL). A nonzero numeric literal divisor needs no guard."""
    integer_division = exp.IntDiv(this=division.left.copy(), expression=division.right.copy())
    divisor = division.right
    if isinstance(divisor, exp.Literal) and divisor.is_number and float(divisor.name) != 0:
        return integer_division
    failure = exp.Anonymous(this="error", expressions=[exp.Literal.string("division by zero")])
    zero = exp.EQ(this=divisor.copy(), expression=exp.Literal.number(0))
    return exp.Case(ifs=[exp.If(this=zero, true=failure)], default=integer_division)


@lru_cache(maxsize=256)
def translate_for_duckdb(sql: str, catalog: Catalog) -> Translation:
    """PostgreSQL text as DuckDB text, with integer division made to truncate."""
    tree = sqlglot.parse_one(sql, read="postgres")
    divisions = list(tree.find_all(exp.Div))
    translated = uncertain = 0
    if divisions:
        schema = {table: dict(columns) for table, columns in catalog}
        kinds: list[tuple[bool, bool]] | None = None
        try:
            typed = qualify(
                tree.copy(),
                schema=schema,
                dialect="postgres",
                validate_qualify_columns=False,
                identify=False,
            )
            typed = annotate_types(typed, schema=schema, dialect="postgres")
            found = list(typed.find_all(exp.Div))
            if len(found) == len(divisions):  # qualification kept the shape: types map back
                kinds = [
                    (
                        d.left.is_type(*exp.DataType.INTEGER_TYPES)
                        and d.right.is_type(*exp.DataType.INTEGER_TYPES),
                        d.left.is_type(exp.DataType.Type.UNKNOWN)
                        or d.right.is_type(exp.DataType.Type.UNKNOWN)
                        or d.left.type is None
                        or d.right.type is None,
                    )
                    for d in found
                ]
        except Exception:  # an unreadable query keeps its divisions as written, all uncertain
            kinds = None
        if kinds is None:
            uncertain = len(divisions)
        else:
            for division, (integer, unknown) in zip(divisions, kinds, strict=True):
                if integer:
                    division.replace(_truncating(division))
                    translated += 1
                elif unknown:
                    uncertain += 1
    text = tree.sql(dialect="duckdb", unsupported_level=ErrorLevel.RAISE)
    return Translation(text, translated, uncertain)
