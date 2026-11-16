"""Comparison of canonical query results under explicit report policies."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, deque
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
from isitright.packs.sql.results import is_error_result


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
    if is_error_result(candidate) and not is_error_result(reference):
        return ComparisonOutcome(
            False,
            f"candidate errors: {candidate.rows[0][0].value}",
            resolve_ordering(policy.ordering, reference_has_order_by=reference_has_order_by)
            is EffectiveOrdering.ORDERED,
        )
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
    """Whether the rows match as multisets under the policy.

    Rows are grouped by everything that must be exactly equal: every non-float cell, and every
    float cell too when the policy compares floats exactly. A reference row can only match a
    candidate row of the same group, so the groups are counted (a counted multiset) and only the
    float cells of a group are matched with a tolerance. Within a group, equal float parts are one
    class with a count, and the classes are matched by an iterative maximum flow, so the result
    does not depend on the order of the rows and no recursion is used.
    """
    reference_groups = _group_rows(reference_rows, policy, "reference")
    candidate_groups = _group_rows(candidate_rows, policy, "candidate")
    if reference_groups.keys() != candidate_groups.keys():
        return False
    for key, reference_floats in reference_groups.items():
        candidate_floats = candidate_groups[key]
        if len(reference_floats) != len(candidate_floats):
            return False
        if not reference_floats[0]:
            continue  # no float cells to compare: equal groups of equal size match
        if not _floats_match(reference_floats, candidate_floats, policy):
            return False
    return True


_NEVER_EQUAL = object()


def _exact_key(value: CanonicalValue, side: str, serial: int) -> object:
    """A hashable key that is equal for two cells exactly when `_values_equal` says so, for a cell
    that is not compared with a tolerance. A cell that equals nothing (NaN, a non-finite decimal)
    gets a key no other cell has."""
    kind = value.kind
    raw = value.value
    if kind is CanonicalValueKind.DECIMAL:
        try:
            number = Decimal(cast(str, raw))
        except InvalidOperation:
            return (kind, _NEVER_EQUAL, side, serial)
        if not number.is_finite():
            return (kind, _NEVER_EQUAL, side, serial)
        return (kind, number)  # equal decimals hash alike (1.0 and 1.00)
    if kind is CanonicalValueKind.FLOAT:
        as_float = float(cast(float, raw))
        if math.isnan(as_float):
            return (kind, _NEVER_EQUAL, side, serial)
        return (kind, as_float)
    if isinstance(raw, list | dict):
        return (kind, json.dumps(raw, sort_keys=True))
    return (kind, raw)


def _group_rows(
    rows: list[list[CanonicalValue]], policy: ComparisonPolicy, side: str
) -> dict[tuple[object, ...], list[tuple[float, ...]]]:
    """Group rows by their exactly-compared cells. Each group lists the float parts of its rows
    (empty tuples when the policy compares floats exactly)."""
    tolerant = policy.float_mode is not FloatComparisonMode.EXACT
    groups: dict[tuple[object, ...], list[tuple[float, ...]]] = {}
    serial = 0
    for row in rows:
        key: list[object] = []
        floats: list[float] = []
        for cell in row:
            serial += 1
            if tolerant and cell.kind is CanonicalValueKind.FLOAT:
                key.append((cell.kind, "within tolerance"))
                floats.append(float(cast(float, cell.value)))
            else:
                key.append(_exact_key(cell, side, serial))
        groups.setdefault(tuple(key), []).append(tuple(floats))
    return groups


def _floats_close(left: float, right: float, policy: ComparisonPolicy) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=policy.float_relative_tolerance,
        abs_tol=policy.float_absolute_tolerance,
    )


def _floats_match(
    reference: list[tuple[float, ...]],
    candidate: list[tuple[float, ...]],
    policy: ComparisonPolicy,
) -> bool:
    reference_classes = Counter(reference)
    candidate_classes = Counter(candidate)
    reference_keys = list(reference_classes)
    candidate_keys = list(candidate_classes)
    edges = [
        [
            index
            for index, other in enumerate(candidate_keys)
            if all(_floats_close(a, b, policy) for a, b in zip(row, other, strict=True))
        ]
        for row in reference_keys
    ]
    return _saturates(
        [reference_classes[key] for key in reference_keys],
        [candidate_classes[key] for key in candidate_keys],
        edges,
    )


def _saturates(left_counts: list[int], right_counts: list[int], edges: list[list[int]]) -> bool:
    """Whether every unit on the left can be matched to a distinct unit on the right: a maximum
    flow from a source through the classes to a sink, by shortest augmenting paths (iterative)."""
    total = sum(left_counts)
    if total != sum(right_counts):
        return False
    n, m = len(left_counts), len(right_counts)
    source, sink = n + m, n + m + 1
    capacity: dict[tuple[int, int], int] = {}
    neighbors: list[list[int]] = [[] for _ in range(n + m + 2)]

    def add(u: int, v: int, units: int) -> None:
        if (u, v) not in capacity:
            capacity[(u, v)] = 0
            capacity.setdefault((v, u), 0)
            neighbors[u].append(v)
            neighbors[v].append(u)
        capacity[(u, v)] += units

    for i, units in enumerate(left_counts):
        add(source, i, units)
        for j in edges[i]:
            add(i, n + j, total)
    for j, units in enumerate(right_counts):
        add(n + j, sink, units)
    flow = 0
    while flow < total:
        parent: dict[int, int] = {source: source}
        queue = deque([source])
        while queue and sink not in parent:
            node = queue.popleft()
            for following in neighbors[node]:
                if following not in parent and capacity[(node, following)] > 0:
                    parent[following] = node
                    queue.append(following)
        if sink not in parent:
            return False
        push = total
        node = sink
        while node != source:
            push = min(push, capacity[(parent[node], node)])
            node = parent[node]
        node = sink
        while node != source:
            capacity[(parent[node], node)] -= push
            capacity[(node, parent[node])] += push
            node = parent[node]
        flow += push
    return True


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


_PLAIN_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_TEXT_LIKE = (
    CanonicalValueKind.TEXT,
    CanonicalValueKind.DATE,
    CanonicalValueKind.TIME,
    CanonicalValueKind.DATETIME,
)


def _number(value: CanonicalValue) -> float | None:
    """A number, or text that reads as a plain number: the benchmark writes both results to CSV
    and reads them back, so the text ``2012`` and the integer 2012 are the same value there."""
    if value.kind in _NUMERIC:
        return float(cast(str | int | float, value.value))
    if value.kind is CanonicalValueKind.TEXT and _PLAIN_NUMBER.fullmatch(str(value.value).strip()):
        return float(str(value.value))
    return None


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
    if left.kind in _TEXT_LIKE and right.kind in _TEXT_LIKE:  # a date and its text are the same
        return str(left.value) == str(right.value)
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
            candidate_names = ", ".join(column.name for column in candidate.columns)
            where = (
                f"no candidate column holds the same values (candidate columns: {candidate_names})"
                if contained
                else "its values differ from the candidate's column in the same position"
            )
            return ComparisonOutcome(False, f"reference column {names[index]}: {where}", ordered)
    return ComparisonOutcome(True, None, ordered)
