"""Domain constraints from a pandera schema (the ``data-schema`` extra).

A pandera ``DataFrameSchema`` is a rule set a team already wrote for a table. The checks that map
onto the core constraint language become constraints (``not_null``, ``unique``, ``range``,
``one_of``); every other check is listed in the notes, never silently dropped, and stays
unchecked. The result is declared by the person who wrote the pandera schema; no model is involved.
"""

from __future__ import annotations

from typing import Any

from isitright.core.constraints import Constraint, NotNull, OneOf, Range, Unique
from isitright.packs.data.mapping import field_name

_BOUNDS: dict[str, tuple[str, bool]] = {
    "greater_than": ("min", True),
    "greater_than_or_equal_to": ("min", False),
    "less_than": ("max", True),
    "less_than_or_equal_to": ("max", False),
}


def constraints_from_pandera(table: str, schema: Any) -> tuple[list[Constraint], list[str]]:
    """Constraints for ``table`` and a note for each pandera check that could not be mapped."""
    rules: list[Constraint] = []
    notes: list[str] = []
    for name, column in schema.columns.items():
        path = f"{table}.{field_name(str(name))}"
        if not column.nullable:
            rules.append(NotNull(path=path))
        if column.unique:
            rules.append(Unique(collection=table, fields=[field_name(str(name))]))
        for check in column.checks:
            stats = dict(check.statistics or {})
            kind = check.name
            if kind == "in_range":
                rules.append(
                    Range(
                        path=path,
                        min=stats["min_value"],
                        max=stats["max_value"],
                        min_exclusive=not stats.get("include_min", True),
                        max_exclusive=not stats.get("include_max", True),
                    )
                )
            elif kind == "isin":
                rules.append(OneOf(path=path, values=list(stats["allowed_values"])))
            elif kind in _BOUNDS:
                side, exclusive = _BOUNDS[kind]
                value = stats[f"{side}_value"]
                rules.append(Range(path=path, **{side: value, f"{side}_exclusive": exclusive}))
            else:
                notes.append(f"{path}: pandera check {kind!r} has no equivalent and is not checked")
    return rules, notes
