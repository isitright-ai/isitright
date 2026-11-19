"""P1: the unordered comparison agrees with the ordered one on nested JSON values.

The ordered comparison tests ``reference.value == candidate.value`` for every kind that is not a
float or a decimal, so [1] equals [1.0], {"n": 2} equals {"n": 2.0} and [True] equals [1]. The
unordered comparison keyed such cells by their JSON text, so it called those rows different: a false
counterexample on array and struct columns that 0.8.0 did not report.
"""

from __future__ import annotations

import random
from typing import Any, cast

import pytest
from pydantic import JsonValue

from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)

UNORDERED = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
ORDERED = ComparisonPolicy(ordering=OrderingPolicy.ORDERED)


def _cell(kind: CanonicalValueKind, value: Any) -> CanonicalValue:
    engine_type = "array" if kind is CanonicalValueKind.ENGINE_SPECIFIC else None
    return CanonicalValue(kind=kind, value=cast(JsonValue, value), engine_type=engine_type)


def _result(rows: list[list[CanonicalValue]]) -> QueryResult:
    width = len(rows[0]) if rows else 1
    return QueryResult(columns=[ResultColumn(name=f"c{i}") for i in range(width)], rows=rows)


def _same(reference: list[list[CanonicalValue]], candidate: list[list[CanonicalValue]]) -> bool:
    """Both comparisons must give this answer for one row on each side."""
    ordered = compare_results(_result(reference), _result(candidate), policy=ORDERED).matches
    unordered = compare_results(_result(reference), _result(candidate), policy=UNORDERED).matches
    assert ordered == unordered, (reference, candidate, ordered, unordered)
    return ordered


@pytest.mark.parametrize("kind", [CanonicalValueKind.JSON, CanonicalValueKind.ENGINE_SPECIFIC])
@pytest.mark.parametrize(
    ("left", "right"),
    [
        ([1], [1.0]),
        ({"n": 2}, {"n": 2.0}),
        ([True], [1]),
        ([[1, {"k": [2]}]], [[1.0, {"k": [2.0]}]]),
        ({"a": 1, "b": [True]}, {"b": [1.0], "a": 1.0}),
    ],
)
def test_nested_values_equal_under_python_equality_match_in_both_comparisons(
    kind: CanonicalValueKind, left: Any, right: Any
) -> None:
    assert _same([[_cell(kind, left)]], [[_cell(kind, right)]]) is True


@pytest.mark.parametrize("kind", [CanonicalValueKind.JSON, CanonicalValueKind.ENGINE_SPECIFIC])
@pytest.mark.parametrize(
    ("left", "right"),
    [
        ([1], [2]),
        ([1, 2], [2, 1]),
        ({"n": 2}, {"m": 2}),
        ([[1]], [1]),
        ([None], [0]),
        ({"a": [1]}, {"a": [1, 1]}),
    ],
)
def test_nested_values_that_differ_differ_in_both_comparisons(
    kind: CanonicalValueKind, left: Any, right: Any
) -> None:
    assert _same([[_cell(kind, left)]], [[_cell(kind, right)]]) is False


def _pool() -> list[Any]:
    """Nested values with equal-under-== twins, near misses and shared substructure."""
    return [
        [1],
        [1.0],
        [True],
        [0],
        [False],
        [0.0],
        [],
        [[]],
        [[1], [2]],
        [[1.0], [2.0]],
        [[2], [1]],
        {"n": 2},
        {"n": 2.0},
        {"n": 3},
        {},
        {"a": [1, {"b": True}]},
        {"a": [1.0, {"b": 1}]},
        {"a": [1, {"b": 0}]},
        {"b": 1, "a": 2},
        {"a": 2, "b": 1.0},
        "text",
        None,
    ]


def test_unordered_comparison_agrees_with_the_ordered_one_on_shuffled_nested_rows() -> None:
    """For many seeded row sets, the answer of the unordered comparison equals a perfect matching
    of the rows built from the ordered comparison's own row equality."""
    rng = random.Random(20261116)
    pool = _pool()
    kinds = [CanonicalValueKind.JSON, CanonicalValueKind.ENGINE_SPECIFIC]
    agreed_true = agreed_false = 0
    for _ in range(400):
        size = rng.randint(1, 6)
        kind = rng.choice(kinds)
        reference = [[_cell(kind, rng.choice(pool))] for _ in range(size)]
        candidate = list(reference)
        rng.shuffle(candidate)
        # a shuffled copy, with some rows swapped for an equal twin or a different value
        for index in range(size):
            if rng.random() < 0.4:
                candidate[index] = [_cell(kind, rng.choice(pool))]
        expected = _perfect_matching_exists(reference, candidate)
        got = compare_results(_result(reference), _result(candidate), policy=UNORDERED).matches
        assert got == expected, (reference, candidate)
        agreed_true += expected
        agreed_false += not expected
    assert agreed_true > 50 and agreed_false > 50  # the pool exercises both answers


def _perfect_matching_exists(
    reference: list[list[CanonicalValue]], candidate: list[list[CanonicalValue]]
) -> bool:
    """Row equality from the ordered comparison (one row against one row); the rows are an
    equivalence relation here, so greedy matching is exact."""
    left_over = list(candidate)
    for row in reference:
        for index, other in enumerate(left_over):
            if compare_results(_result([row]), _result([other]), policy=ORDERED).matches:
                del left_over[index]
                break
        else:
            return False
    return not left_over
