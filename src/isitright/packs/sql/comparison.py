"""Comparison of canonical query results under explicit report policies."""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

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


DifferenceKind = Literal["error", "row_count", "row_values"]


def difference_kind(reference: QueryResult, candidate: QueryResult) -> DifferenceKind:
    """The kind of difference between two results that do not match: the candidate errors where
    the reference does not, the row counts differ, or the counts agree and the values do not.

    Minimization keeps a smaller world only when its difference has the kind that was found, so a
    world never drifts from one disagreement to another.
    """
    if is_error_result(candidate) and not is_error_result(reference):
        return "error"
    if len(reference.rows) != len(candidate.rows):
        return "row_count"
    return "row_values"


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
    return (kind, _nested_key(raw))


def _nested_key(value: object) -> object:
    """A hashable key for a JSON value that is equal exactly when Python's ``==`` is, which is what
    the ordered comparison uses for these kinds: [1] and [1.0], {"n": 2} and {"n": 2.0}, and [True]
    and [1] are equal, and the key order of an object does not matter."""
    if isinstance(value, list):
        return ("list", tuple(_nested_key(item) for item in value))
    if isinstance(value, dict):
        return ("dict", frozenset((key, _nested_key(item)) for key, item in value.items()))
    return value


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


def _window(value: float, policy: ComparisonPolicy) -> float | None:
    """A distance that every float close to ``value`` lies within, or None when there is no bound.

    ``isclose`` holds when |a - b| <= max(rel * max(|a|, |b|), abs). Take the b with the larger
    magnitude: |b| <= |a| + |a - b|, so for rel < 1 the distance is at most rel * |a| / (1 - rel),
    or abs. The bound is widened a little so rounding cannot exclude a close value; the candidates
    inside the window are still checked with ``isclose`` itself.
    """
    rel = policy.float_relative_tolerance
    if rel >= 1.0:
        return None
    reach = max(rel * abs(value) / (1.0 - rel), policy.float_absolute_tolerance)
    return reach * (1.0 + 1e-9) + 1e-300


def _floats_match(
    reference: list[tuple[float, ...]],
    candidate: list[tuple[float, ...]],
    policy: ComparisonPolicy,
) -> bool:
    """Whether the float parts of two equally sized groups of rows can be paired one to one, every
    pair within the tolerance in every position.

    Equal float parts are one class with a count. Each reference class looks only at the candidate
    classes whose first float lies in a window around its own (found by bisection on the sorted
    first floats), so the work does not grow with the product of the two sides. Equal classes are
    paired first; what is left is paired by shortest augmenting paths, one at a time, which does not
    use recursion. This decides the same question as a maximum flow over every close pair.
    """
    reference_classes = Counter(reference)
    candidate_classes = Counter(candidate)
    reference_keys = list(reference_classes)
    candidate_keys = list(candidate_classes)
    supply = [reference_classes[key] for key in reference_keys]
    demand = [candidate_classes[key] for key in candidate_keys]
    if sum(supply) != sum(demand):
        return False

    # candidate classes that can match something, ordered by their first float
    order = sorted(
        (j for j, key in enumerate(candidate_keys) if not any(math.isnan(x) for x in key)),
        key=lambda j: candidate_keys[j][0] if candidate_keys[j] else 0.0,
    )
    firsts = [candidate_keys[j][0] if candidate_keys[j] else 0.0 for j in order]
    edge_cache: dict[int, list[int]] = {}

    def edges(i: int) -> list[int]:
        cached = edge_cache.get(i)
        if cached is not None:
            return cached
        row = reference_keys[i]
        found: list[int] = []
        if not any(math.isnan(x) for x in row):
            if not row:
                low, high = 0, len(order)
            else:
                first = row[0]
                reach = _window(first, policy) if math.isfinite(first) else 0.0
                if reach is None:
                    low, high = 0, len(order)
                else:
                    low = bisect_left(firsts, first - reach)
                    high = bisect_right(firsts, first + reach)
            for position in range(low, high):
                j = order[position]
                other = candidate_keys[j]
                if all(_floats_close(a, b, policy) for a, b in zip(row, other, strict=True)):
                    found.append(j)
        edge_cache[i] = found
        return found

    flow: dict[tuple[int, int], int] = {}
    matched_to: list[dict[int, int]] = [{} for _ in candidate_keys]  # j -> {i: units}
    left = list(supply)
    free = list(demand)

    def push(i: int, j: int, units: int) -> None:
        flow[(i, j)] = flow.get((i, j), 0) + units
        matched_to[j][i] = matched_to[j].get(i, 0) + units

    # pair equal classes first (a class equals itself unless it holds a NaN)
    index_of = {key: j for j, key in enumerate(candidate_keys)}
    for i, key in enumerate(reference_keys):
        j = index_of.get(key)
        if j is not None and not any(math.isnan(x) for x in key):
            units = min(left[i], free[j])
            if units:
                push(i, j, units)
                left[i] -= units
                free[j] -= units

    for start in range(len(reference_keys)):
        while left[start] > 0:
            if not _augment(start, left, free, edges, flow, matched_to):
                return False
    return True


def _augment(
    start: int,
    left: list[int],
    free: list[int],
    edges: Callable[[int], list[int]],
    flow: dict[tuple[int, int], int],
    matched_to: list[dict[int, int]],
) -> bool:
    """Find one shortest augmenting path from reference class ``start`` (which still has units to
    place) to a candidate class with a free unit, alternating over unused and used pairs, and push
    the largest amount it can carry. Returns False when there is none."""
    # nodes are ("r", i) or ("c", j); parent links rebuild the path
    parent: dict[tuple[str, int], tuple[str, int] | None] = {("r", start): None}
    queue: deque[tuple[str, int]] = deque([("r", start)])
    end: int | None = None
    while queue and end is None:
        kind, index = queue.popleft()
        if kind == "r":
            for j in edges(index):
                reached = ("c", j)
                if reached in parent:
                    continue
                parent[reached] = (kind, index)
                if free[j] > 0:
                    end = j
                    break
                queue.append(reached)
        else:
            for i in matched_to[index]:
                taken = ("r", i)
                if taken not in parent and matched_to[index][i] > 0:
                    parent[taken] = (kind, index)
                    queue.append(taken)
    if end is None:
        return False
    # the amount: what the start still has, what the end still has, and the flow taken back
    amount = min(left[start], free[end])
    node: tuple[str, int] | None = ("c", end)
    while node is not None and parent[node] is not None:
        before = parent[node]
        assert before is not None
        if node[0] == "r":  # a step back along a used pair: from candidate ``before`` to ref node
            amount = min(amount, matched_to[before[1]][node[1]])
        node = before
    node = ("c", end)
    while parent[node] is not None:
        before = parent[node]
        assert before is not None
        if node[0] == "c":  # forward: reference class ``before`` -> candidate class node
            flow[(before[1], node[1])] = flow.get((before[1], node[1]), 0) + amount
            matched_to[node[1]][before[1]] = matched_to[node[1]].get(before[1], 0) + amount
        else:  # backward: candidate class ``before`` gives back to reference class node
            flow[(node[1], before[1])] -= amount
            matched_to[before[1]][node[1]] -= amount
        node = before
    left[start] -= amount
    free[end] -= amount
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
