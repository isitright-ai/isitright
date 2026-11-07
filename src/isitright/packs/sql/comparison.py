"""Comparison of canonical query results under explicit report policies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast

from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ColumnComparisonPolicy,
    ComparisonPolicy,
    EffectiveOrdering,
    FloatComparisonMode,
    OrderingPolicy,
    QueryResult,
)


class ComparisonError(ValueError):
    """Raised when a selected comparison policy is ambiguous for the results."""


@dataclass(frozen=True, slots=True)
class ComparisonOutcome:
    matches: bool
    difference: str | None
    ordered: bool


def compare_results(
    reference: QueryResult,
    candidate: QueryResult,
    *,
    policy: ComparisonPolicy,
    reference_has_order_by: bool = False,
) -> ComparisonOutcome:
    """Compare two query results, retaining type and duplicate semantics."""
    if policy.null_as_zero:
        reference, candidate = _zero_nulls(reference), _zero_nulls(candidate)
    if (
        policy.columns is ColumnComparisonPolicy.CONTAINED
        or policy.column_vectors
        or policy.reference_columns is not None
    ):
        return _compare_vectors(reference, candidate, policy, reference_has_order_by)
    reference_rows, candidate_rows, column_difference = _align_columns(
        reference, candidate, policy.columns
    )
    effective_ordering = resolve_ordering(
        policy.ordering,
        reference_has_order_by=reference_has_order_by,
    )
    ordered = effective_ordering is EffectiveOrdering.ORDERED

    if column_difference is not None:
        return ComparisonOutcome(
            matches=False,
            difference=column_difference,
            ordered=ordered,
        )

    if len(reference_rows) != len(candidate_rows):
        return ComparisonOutcome(
            matches=False,
            difference=(
                f"row count differs: reference={len(reference_rows)}, "
                f"candidate={len(candidate_rows)}"
            ),
            ordered=ordered,
        )

    if ordered:
        for index, (reference_row, candidate_row) in enumerate(
            zip(reference_rows, candidate_rows, strict=True)
        ):
            if not _rows_equal(reference_row, candidate_row, policy):
                return ComparisonOutcome(
                    matches=False,
                    difference=f"ordered row {index} differs",
                    ordered=True,
                )
        return ComparisonOutcome(matches=True, difference=None, ordered=True)

    if _unordered_rows_match(reference_rows, candidate_rows, policy):
        return ComparisonOutcome(matches=True, difference=None, ordered=False)
    return ComparisonOutcome(
        matches=False,
        difference="unordered row multiset differs",
        ordered=False,
    )


def _unordered_rows_match(
    reference_rows: list[list[CanonicalValue]],
    candidate_rows: list[list[CanonicalValue]],
    policy: ComparisonPolicy,
) -> bool:
    """Find a complete row matching even when float tolerance overlaps."""
    matched_reference_by_candidate: list[int | None] = [None] * len(candidate_rows)

    def assign(reference_index: int, visited_candidates: set[int]) -> bool:
        for candidate_index, candidate_row in enumerate(candidate_rows):
            if candidate_index in visited_candidates or not _rows_equal(
                reference_rows[reference_index], candidate_row, policy
            ):
                continue
            visited_candidates.add(candidate_index)
            previous_reference = matched_reference_by_candidate[candidate_index]
            if previous_reference is None or assign(previous_reference, visited_candidates):
                matched_reference_by_candidate[candidate_index] = reference_index
                return True
        return False

    return all(assign(index, set()) for index in range(len(reference_rows)))


def _align_columns(
    reference: QueryResult,
    candidate: QueryResult,
    policy: ColumnComparisonPolicy,
) -> tuple[list[list[CanonicalValue]], list[list[CanonicalValue]], str | None]:
    reference_names = [column.name for column in reference.columns]
    candidate_names = [column.name for column in candidate.columns]
    if len(reference_names) != len(candidate_names):
        return (
            reference.rows,
            candidate.rows,
            f"column count differs: reference={len(reference_names)}, "
            f"candidate={len(candidate_names)}",
        )

    if policy is ColumnComparisonPolicy.POSITIONAL:
        return reference.rows, candidate.rows, None
    if policy is ColumnComparisonPolicy.NAMES_AND_POSITIONS:
        if reference_names != candidate_names:
            return reference.rows, candidate.rows, "column names or positions differ"
        return reference.rows, candidate.rows, None

    if len(set(reference_names)) != len(reference_names) or len(set(candidate_names)) != len(
        candidate_names
    ):
        raise ComparisonError("by_name comparison requires unique result column names")
    if set(reference_names) != set(candidate_names):
        return reference.rows, candidate.rows, "column names differ"
    candidate_indexes = [candidate_names.index(name) for name in reference_names]
    aligned_candidate = [[row[index] for index in candidate_indexes] for row in candidate.rows]
    return reference.rows, aligned_candidate, None


def resolve_ordering(
    ordering: OrderingPolicy,
    *,
    reference_has_order_by: bool,
) -> EffectiveOrdering:
    """Resolve ordering, using only the reference query as AUTO's contract."""
    if ordering is OrderingPolicy.ORDERED:
        return EffectiveOrdering.ORDERED
    if ordering is OrderingPolicy.UNORDERED:
        return EffectiveOrdering.UNORDERED
    if reference_has_order_by:
        return EffectiveOrdering.ORDERED
    return EffectiveOrdering.UNORDERED


def _rows_equal(
    reference: list[CanonicalValue],
    candidate: list[CanonicalValue],
    policy: ComparisonPolicy,
) -> bool:
    return len(reference) == len(candidate) and all(
        _values_equal(left, right, policy) for left, right in zip(reference, candidate, strict=True)
    )


def _values_equal(
    reference: CanonicalValue,
    candidate: CanonicalValue,
    policy: ComparisonPolicy,
) -> bool:
    if reference.kind is not candidate.kind:
        return False
    if reference.kind is CanonicalValueKind.DECIMAL:
        try:
            left = Decimal(cast(str, reference.value))
            right = Decimal(cast(str, candidate.value))
            return left.is_finite() and right.is_finite() and left == right
        except InvalidOperation:
            return False
    if reference.kind is not CanonicalValueKind.FLOAT:
        return reference.value == candidate.value
    reference_float = cast(float, reference.value)
    candidate_float = cast(float, candidate.value)
    if policy.float_mode is FloatComparisonMode.EXACT:
        return reference_float == candidate_float
    return math.isclose(
        reference_float,
        candidate_float,
        rel_tol=policy.float_relative_tolerance,
        abs_tol=policy.float_absolute_tolerance,
    )


# --- benchmark-style comparison: columns as vectors ----------------------------------------------

_NUMERIC = (CanonicalValueKind.INTEGER, CanonicalValueKind.FLOAT, CanonicalValueKind.DECIMAL)


def _zero_nulls(result: QueryResult) -> QueryResult:
    zero = CanonicalValue(kind=CanonicalValueKind.INTEGER, value=0)
    rows = [
        [zero if cell.kind is CanonicalValueKind.NULL else cell for cell in row]
        for row in result.rows
    ]
    return QueryResult(columns=result.columns, rows=rows)


def _number(value: CanonicalValue) -> float | None:
    if value.kind not in _NUMERIC:
        return None
    return float(cast(str | int | float, value.value))


def _sort_key(value: CanonicalValue) -> tuple[int, float, str]:
    number = _number(value)
    if number is not None:
        return (0, number, "")
    return (2 if value.kind is CanonicalValueKind.NULL else 1, 0.0, str(value.value))


def _columns_of(result: QueryResult) -> list[list[CanonicalValue]]:
    width = len(result.columns)
    return [[row[i] for row in result.rows] for i in range(width)]


def _vector_values_equal(left: CanonicalValue, right: CanonicalValue, tolerance: float) -> bool:
    if left.kind is CanonicalValueKind.NULL and right.kind is CanonicalValueKind.NULL:
        return True
    a, b = _number(left), _number(right)
    if a is not None and b is not None:
        return math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance)
    return left.kind is right.kind and left.value == right.value


def _vectors_match(
    left: list[CanonicalValue], right: list[CanonicalValue], *, ordered: bool, tolerance: float
) -> bool:
    if len(left) != len(right):
        return False
    if not ordered:
        left, right = sorted(left, key=_sort_key), sorted(right, key=_sort_key)
    return all(_vector_values_equal(a, b, tolerance) for a, b in zip(left, right, strict=True))


def _compare_vectors(
    reference: QueryResult,
    candidate: QueryResult,
    policy: ComparisonPolicy,
    reference_has_order_by: bool,
) -> ComparisonOutcome:
    """Each reference column must equal a candidate column (any position if ``contained``, the
    same position otherwise); an unordered comparison sorts every column on its own."""
    ordered = resolve_ordering(policy.ordering, reference_has_order_by=reference_has_order_by) is (
        EffectiveOrdering.ORDERED
    )
    wanted, got = _columns_of(reference), _columns_of(candidate)
    if policy.reference_columns is not None:
        if any(not 0 <= i < len(wanted) for i in policy.reference_columns):
            raise ComparisonError(
                f"reference_columns {policy.reference_columns} do not fit the reference's "
                f"{len(wanted)} columns"
            )
        wanted = [wanted[i] for i in policy.reference_columns]
        names = [reference.columns[i].name for i in policy.reference_columns]
    else:
        names = [column.name for column in reference.columns]
    tolerance = policy.float_absolute_tolerance
    contained = (
        policy.columns is ColumnComparisonPolicy.CONTAINED or policy.reference_columns is not None
    )
    if not contained and len(wanted) != len(got):
        return ComparisonOutcome(
            False,
            f"column count differs: reference={len(wanted)}, candidate={len(got)}",
            ordered,
        )
    if len(reference.rows) != len(candidate.rows):
        return ComparisonOutcome(
            False,
            f"row count differs: reference={len(reference.rows)}, candidate={len(candidate.rows)}",
            ordered,
        )
    for index, vector in enumerate(wanted):
        pool = got if contained else [got[index]]
        if not any(
            _vectors_match(vector, other, ordered=ordered, tolerance=tolerance) for other in pool
        ):
            return ComparisonOutcome(
                False,
                f"reference column {names[index]} has no matching candidate column",
                ordered,
            )
    return ComparisonOutcome(True, None, ordered)
