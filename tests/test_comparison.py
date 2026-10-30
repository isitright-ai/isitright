from typing import cast

import pytest
from pydantic import JsonValue

from isitright.packs.sql.comparison import ComparisonError, compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ColumnComparisonPolicy,
    ComparisonPolicy,
    FloatComparisonMode,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)


def _value(kind: CanonicalValueKind, value: object) -> CanonicalValue:
    return CanonicalValue(kind=kind, value=cast(JsonValue, value))


def _result(names: list[str], rows: list[list[CanonicalValue]]) -> QueryResult:
    return QueryResult(columns=[ResultColumn(name=name) for name in names], rows=rows)


def test_unordered_comparison_is_a_multiset() -> None:
    one = _value(CanonicalValueKind.INTEGER, 1)
    two = _value(CanonicalValueKind.INTEGER, 2)
    reference = _result(["value"], [[one], [two], [two]])
    reordered = _result(["other"], [[two], [one], [two]])
    missing_duplicate = _result(["value"], [[one], [two]])
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)

    assert compare_results(reference, reordered, policy=policy).matches is True
    assert compare_results(reference, missing_duplicate, policy=policy).matches is False


def test_auto_ordering_follows_only_reference_top_level_order_by() -> None:
    one = _value(CanonicalValueKind.INTEGER, 1)
    two = _value(CanonicalValueKind.INTEGER, 2)
    reference = _result(["value"], [[one], [two]])
    candidate = _result(["value"], [[two], [one]])

    unordered = compare_results(reference, candidate, policy=ComparisonPolicy())
    reference_ordered = compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(),
        reference_has_order_by=True,
    )

    assert unordered.matches is True
    assert reference_ordered.matches is False
    assert reference_ordered.ordered is True


def test_explicit_ordered_comparison_can_match() -> None:
    value = _value(CanonicalValueKind.INTEGER, 1)
    result = _result(["value"], [[value]])
    outcome = compare_results(
        result,
        result,
        policy=ComparisonPolicy(ordering=OrderingPolicy.ORDERED),
    )
    assert outcome.matches is True
    assert outcome.ordered is True


def test_column_policies_are_explicit() -> None:
    one = _value(CanonicalValueKind.INTEGER, 1)
    text = _value(CanonicalValueKind.TEXT, "x")
    reference = _result(["id", "label"], [[one, text]])
    candidate = _result(["label", "id"], [[text, one]])

    assert compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(columns=ColumnComparisonPolicy.BY_NAME),
    ).matches
    assert not compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(columns=ColumnComparisonPolicy.POSITIONAL),
    ).matches
    assert not compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(columns=ColumnComparisonPolicy.NAMES_AND_POSITIONS),
    ).matches


def test_by_name_rejects_duplicate_names() -> None:
    value = _value(CanonicalValueKind.INTEGER, 1)
    result = _result(["value", "value"], [[value, value]])
    with pytest.raises(ComparisonError, match="unique"):
        compare_results(
            result,
            result,
            policy=ComparisonPolicy(columns=ColumnComparisonPolicy.BY_NAME),
        )


def test_by_name_detects_different_names() -> None:
    value = _value(CanonicalValueKind.INTEGER, 1)
    reference = _result(["reference_name"], [[value]])
    candidate = _result(["candidate_name"], [[value]])
    outcome = compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(columns=ColumnComparisonPolicy.BY_NAME),
    )
    assert outcome.matches is False
    assert outcome.difference == "column names differ"


def test_storage_classes_and_float_tolerance_are_distinct() -> None:
    integer = _result(["value"], [[_value(CanonicalValueKind.INTEGER, 1)]])
    real = _result(["value"], [[_value(CanonicalValueKind.FLOAT, 1.0)]])
    near_real = _result(["value"], [[_value(CanonicalValueKind.FLOAT, 1.0 + 1e-10)]])

    assert not compare_results(integer, real, policy=ComparisonPolicy()).matches
    assert compare_results(real, near_real, policy=ComparisonPolicy()).matches
    assert not compare_results(
        real,
        near_real,
        policy=ComparisonPolicy(float_mode=FloatComparisonMode.EXACT),
    ).matches


def test_unordered_float_matching_is_not_greedy() -> None:
    reference = _result(
        ["value"],
        [
            [_value(CanonicalValueKind.FLOAT, 0.0)],
            [_value(CanonicalValueKind.FLOAT, 0.2)],
        ],
    )
    candidate = _result(
        ["value"],
        [
            [_value(CanonicalValueKind.FLOAT, 0.1)],
            [_value(CanonicalValueKind.FLOAT, 0.0)],
        ],
    )
    policy = ComparisonPolicy(
        ordering=OrderingPolicy.UNORDERED,
        float_relative_tolerance=0,
        float_absolute_tolerance=0.11,
    )

    assert compare_results(reference, candidate, policy=policy).matches is True


def test_column_count_mismatch_is_detected_even_without_rows() -> None:
    left = _result(["one"], [])
    right = _result(["one", "two"], [])
    outcome = compare_results(left, right, policy=ComparisonPolicy())
    assert outcome.matches is False
    assert outcome.difference == "column count differs: reference=1, candidate=2"


def test_decimal_comparison_is_exact_but_not_sensitive_to_display_scale() -> None:
    def decimal(value: str) -> QueryResult:
        return _result(["value"], [[_value(CanonicalValueKind.DECIMAL, value)]])

    assert compare_results(decimal("1.0"), decimal("1.00"), policy=ComparisonPolicy()).matches
    assert compare_results(decimal("-0"), decimal("0.000"), policy=ComparisonPolicy()).matches
    assert not compare_results(
        decimal("123456789012345678901234567890.1"),
        decimal("123456789012345678901234567890.2"),
        policy=ComparisonPolicy(),
    ).matches
    assert not compare_results(decimal("NaN"), decimal("NaN"), policy=ComparisonPolicy()).matches
    assert not compare_results(decimal("bad"), decimal("bad"), policy=ComparisonPolicy()).matches
