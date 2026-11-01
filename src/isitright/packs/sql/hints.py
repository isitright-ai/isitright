"""Hints harvested from SQL programs with SQLGlot.

``column``: a column either program reads. ``literal``: a literal in either program, paired with
every referenced column it could be compared to. ``scope``: a table either program reads (so
duplicates, empty relations and dangling references there are tried first).
"""

from __future__ import annotations

from typing import Any

from isitright.core.entities import EntitySchema, ModelError
from isitright.core.hints import Hint, HintKind, Hints, Provenance, register_hint_kind
from isitright.packs.sql.analysis import QueryGuidance
from isitright.packs.sql.mapping import SqlModel

_NUMERIC = {"int", "float", "decimal"}


def _check_column(schema: EntitySchema, hint: Hint) -> None:
    schema.collection(hint.args["collection"]).field(hint.args["field"])


def _check_literal(schema: EntitySchema, hint: Hint) -> None:
    schema.resolve(hint.args["path"])


register_hint_kind(HintKind("column", _check_column))
register_hint_kind(HintKind("literal", _check_literal))


def hints_from_guidance(model: SqlModel, guidance: QueryGuidance) -> Hints:
    hints: list[Hint] = []
    referenced: list[tuple[str, str, str]] = []
    for table in model.db.tables:
        if table.name not in guidance.tables:
            continue
        hints.append(
            Hint(
                kind="scope",
                name=f"scope:{table.name}",
                provenance=Provenance.HARVESTED_PROGRAM,
                args={"collection": table.name},
            )
        )
        for column in table.columns:
            if column.hidden or not guidance.references_column(table.name, column.name):
                continue
            field_type = model.schema.collection(table.name).field(column.name).type
            referenced.append((table.name, column.name, field_type))
            hints.append(
                Hint(
                    kind="column",
                    name=f"column:{table.name}.{column.name}",
                    provenance=Provenance.HARVESTED_PROGRAM,
                    args={"collection": table.name, "field": column.name},
                )
            )
    for literal in guidance.literals:
        for table_name, column_name, kind in referenced:
            if guidance.bound_literals and not _is_bound(
                guidance, table_name, column_name, literal
            ):
                continue  # the query never compares this column with this literal
            primary = model.db.table(table_name)
            if any(c.name == column_name and c.primary_key_position for c in primary.columns):
                continue
            numeric = isinstance(literal, int | float) and not isinstance(literal, bool)
            textual = isinstance(literal, str)
            if (numeric and kind in _NUMERIC | {"json"}) or (textual and kind in {"text", "json"}):
                if kind == "json" and numeric != _is_numeric_declared(
                    model, table_name, column_name
                ):
                    continue
                hints.append(
                    Hint(
                        kind="literal",
                        name=f"literal:{table_name}.{column_name}={literal!r}",
                        provenance=Provenance.HARVESTED_PROGRAM,
                        args={"path": f"{table_name}.{column_name}", "value": literal},
                    )
                )
    return Hints(hints)


def _is_bound(guidance: QueryGuidance, table: str, column: str, literal: Any) -> bool:
    return any(
        name == column
        and qualifier in (None, table)
        and value == literal
        and type(value) is type(literal)
        for qualifier, name, value in guidance.bound_literals
    )


def _is_numeric_declared(model: SqlModel, table: str, column: str) -> bool:
    """SQLite fields are untyped in the entity model: use the declared affinity instead."""
    declared = next(c for c in model.db.table(table).columns if c.name == column).declared_type
    upper = declared.upper()
    return any(t in upper for t in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC"))


def validate_hints(model: SqlModel, hints: Hints) -> None:
    try:
        hints.validate(model.schema)
    except ModelError as error:  # pragma: no cover - harvested hints always resolve
        raise ValueError(str(error)) from error
