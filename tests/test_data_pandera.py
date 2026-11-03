"""Constraints imported from a pandera schema; unmapped checks are listed, not dropped."""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")
pa = pytest.importorskip("pandera.pandas")

from isitright.core.constraints import NotNull, OneOf, Range, Unique  # noqa: E402
from isitright.packs.data.pandera_import import constraints_from_pandera  # noqa: E402


def test_pandera_checks_become_core_constraints() -> None:
    schema = pa.DataFrameSchema(
        {
            "a": pa.Column(int, [pa.Check.in_range(0, 10), pa.Check.isin([1, 2])]),
            "b": pa.Column(float, pa.Check.gt(0), unique=True, nullable=True),
            "c": pa.Column(float, pa.Check.le(5), nullable=True),
            "d": pa.Column(str, pa.Check.str_length(3), nullable=True),
        }
    )
    rules, notes = constraints_from_pandera("t", schema)
    kinds = [type(r) for r in rules]
    assert kinds.count(NotNull) == 1 and Unique in kinds and OneOf in kinds
    ranges = {r.path: r for r in rules if isinstance(r, Range)}
    assert (ranges["t.a"].min, ranges["t.a"].max) == (0, 10)
    assert ranges["t.b"].min == 0 and ranges["t.b"].min_exclusive
    assert ranges["t.c"].max == 5 and not ranges["t.c"].max_exclusive
    assert len(notes) == 1 and "str_length" in notes[0] and "not checked" in notes[0]
