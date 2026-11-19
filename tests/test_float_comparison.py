"""P5: rows that cannot be keyed exactly (floats under a tolerance) compare in near-linear time,
with the answers of the previous implementation.

0.8.1 matched such rows by building every reference-candidate edge (quadratic) and a flow over
them: a result with one float column and 3,000 distinct rows took 6.5 s and 10,000 rows 88 s. The
matching now looks only at candidates inside a tolerance-safe window, pairs equal rows first and
augments the rest iteratively. The previous code is kept below, verbatim, as the oracle.
"""

from __future__ import annotations

import math
import random
import time
from collections import Counter, deque
from typing import Any, cast

import pytest
from pydantic import JsonValue

from isitright.packs.sql.comparison import _floats_match, _rows_equal, compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)

# -- the previous implementation (0.8.1 before this change), unchanged --------------------------


def _previous_floats_close(left: float, right: float, policy: ComparisonPolicy) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=policy.float_relative_tolerance,
        abs_tol=policy.float_absolute_tolerance,
    )


def _previous_floats_match(
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
            if all(_previous_floats_close(a, b, policy) for a, b in zip(row, other, strict=True))
        ]
        for row in reference_keys
    ]
    return _previous_saturates(
        [reference_classes[key] for key in reference_keys],
        [candidate_classes[key] for key in candidate_keys],
        edges,
    )


def _previous_saturates(
    left_counts: list[int], right_counts: list[int], edges: list[list[int]]
) -> bool:
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


# -- differential tests ---------------------------------------------------------------------------

BOUNDARY = [
    0.0,
    -0.0,
    1.0,
    1.0 + 1e-9,
    1.0 + 0.9e-9,
    1.0 + 1.1e-9,
    1.0 - 1e-9,
    1e-12,
    2e-12,
    0.9e-12,
    1.1e-12,
    -1e-12,
    5e-324,
    1e308,
    -1e308,
    100.0,
    109.0,
    91.0,
    2.5,
    -2.5,
    float("inf"),
    float("-inf"),
    float("nan"),
]
POLICIES = [
    ComparisonPolicy(),  # rel 1e-9, abs 1e-12
    ComparisonPolicy(float_relative_tolerance=0.1, float_absolute_tolerance=0.0),
    ComparisonPolicy(float_relative_tolerance=0.0, float_absolute_tolerance=0.5),
    ComparisonPolicy(float_relative_tolerance=0.0, float_absolute_tolerance=0.0),
    ComparisonPolicy(float_relative_tolerance=0.99, float_absolute_tolerance=0.0),
    ComparisonPolicy(float_relative_tolerance=1.0, float_absolute_tolerance=0.0),
    ComparisonPolicy(float_relative_tolerance=3.0, float_absolute_tolerance=1e-12),
]


def _row(rng: random.Random, width: int, pool: list[float]) -> tuple[float, ...]:
    return tuple(rng.choice(pool) for _ in range(width))


def test_the_matching_gives_the_answers_of_the_previous_implementation() -> None:
    rng = random.Random(20261116)
    answers = Counter()
    started = time.perf_counter()
    for _ in range(3000):
        policy = rng.choice(POLICIES)
        width = rng.choice([1, 1, 2])
        pool = rng.sample(BOUNDARY, rng.randint(2, 8))
        size = rng.randint(0, 7)
        reference = [_row(rng, width, pool) for _ in range(size)]
        if rng.random() < 0.6:  # a shuffled copy, some rows swapped for another value
            candidate = list(reference)
            rng.shuffle(candidate)
            for index in range(size):
                if rng.random() < 0.3:
                    candidate[index] = _row(rng, width, pool)
        else:
            candidate = [_row(rng, width, pool) for _ in range(size)]
        expected = _previous_floats_match(reference, candidate, policy)
        got = _floats_match(reference, candidate, policy)
        assert got == expected, (reference, candidate, policy)
        answers[expected] += 1
    assert answers[True] > 300 and answers[False] > 300  # both answers are exercised
    assert time.perf_counter() - started < 5.0


def test_dense_clusters_need_augmenting_paths_and_still_agree_with_the_previous_answer() -> None:
    """Many values within tolerance of several others, with counts: a pairing that exists only if
    earlier choices are undone (the answer of the previous maximum flow)."""
    rng = random.Random(11)
    policy = ComparisonPolicy(float_relative_tolerance=0.1, float_absolute_tolerance=0.0)
    answers: Counter[bool] = Counter()
    for _ in range(400):
        pool = [rng.uniform(80.0, 130.0) for _ in range(rng.randint(4, 14))]
        size = rng.randint(8, 40)
        reference = [(rng.choice(pool),) for _ in range(size)]
        candidate = [(rng.choice(pool) * rng.uniform(0.93, 1.07),) for _ in range(size)]
        expected = _previous_floats_match(reference, candidate, policy)
        assert _floats_match(reference, candidate, policy) == expected
        answers[expected] += 1
    assert answers[True] > 40 and answers[False] > 40


def _cell(value: float) -> CanonicalValue:
    return CanonicalValue(kind=CanonicalValueKind.FLOAT, value=cast(JsonValue, value))


def _result(rows: list[list[CanonicalValue]], width: int) -> QueryResult:
    return QueryResult(columns=[ResultColumn(name=f"c{i}") for i in range(width)], rows=rows)


def _row_equal_matching(
    reference: list[list[CanonicalValue]],
    candidate: list[list[CanonicalValue]],
    policy: ComparisonPolicy,
) -> bool:
    """A perfect matching by Kuhn's algorithm on the ordered comparison's own row equality."""
    if len(reference) != len(candidate):
        return False
    owner: dict[int, int] = {}

    def assign(i: int, seen: set[int]) -> bool:
        for j, other in enumerate(candidate):
            if j not in seen and _rows_equal(reference[i], other, policy):
                seen.add(j)
                if j not in owner or assign(owner[j], seen):
                    owner[j] = i
                    return True
        return False

    return all(assign(i, set()) for i in range(len(reference)))


def test_the_whole_unordered_comparison_agrees_with_a_matching_on_row_equality() -> None:
    rng = random.Random(7)
    seen: Counter[bool] = Counter()
    for _ in range(1500):
        policy = rng.choice(POLICIES).model_copy(update={"ordering": OrderingPolicy.UNORDERED})
        width = rng.choice([1, 2])
        pool = rng.sample(BOUNDARY, rng.randint(2, 7))
        size = rng.randint(1, 6)
        reference = [[_cell(v) for v in _row(rng, width, pool)] for _ in range(size)]
        candidate = list(reference)
        rng.shuffle(candidate)
        for index in range(size):
            if rng.random() < 0.3:
                candidate[index] = [_cell(v) for v in _row(rng, width, pool)]
        expected = _row_equal_matching(reference, candidate, policy)
        got = compare_results(
            _result(reference, width), _result(candidate, width), policy=policy
        ).matches
        assert got == expected, (reference, candidate, policy)
        seen[expected] += 1
    assert seen[True] > 100 and seen[False] > 100


# -- timing -------------------------------------------------------------------------------------


def _distinct_floats(count: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    values: set[float] = set()
    while len(values) < count:
        values.add(rng.uniform(-1e6, 1e6))
    return sorted(values)


def test_10000_distinct_float_rows_compare_in_under_two_seconds() -> None:
    values = _distinct_floats(10_000, 1)
    reference = [[_cell(v)] for v in values]
    shuffled = list(reference)
    random.Random(2).shuffle(shuffled)
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    started = time.perf_counter()
    outcome = compare_results(_result(reference, 1), _result(shuffled, 1), policy=policy)
    seconds = time.perf_counter() - started
    assert outcome.matches is True
    assert seconds < 2.0, f"{seconds:.2f}s"


def test_10000_float_rows_that_differ_within_the_tolerance_compare_in_under_two_seconds() -> None:
    values = _distinct_floats(10_000, 3)
    reference = [[_cell(v)] for v in values]
    nudged = [[_cell(v * (1 + 5e-10))] for v in values]  # inside the default relative tolerance
    random.Random(4).shuffle(nudged)
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    started = time.perf_counter()
    outcome = compare_results(_result(reference, 1), _result(nudged, 1), policy=policy)
    seconds = time.perf_counter() - started
    assert outcome.matches is True
    assert seconds < 2.0, f"{seconds:.2f}s"
    too_far = [[_cell(v * (1 + 5e-9))] for v in values]  # outside it: no row can match
    assert not compare_results(_result(reference, 1), _result(too_far, 1), policy=policy).matches


def test_one_row_outside_the_tolerance_is_still_found_among_10000() -> None:
    values = _distinct_floats(10_000, 5)
    reference = [[_cell(v)] for v in values]
    changed = [[_cell(v)] for v in values]
    changed[1234] = [_cell(values[1234] + 1.0)]
    random.Random(6).shuffle(changed)
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    started = time.perf_counter()
    outcome = compare_results(_result(reference, 1), _result(changed, 1), policy=policy)
    assert outcome.matches is False
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize("count", [3_000])
def test_a_mismatch_in_a_large_float_result_is_reported_quickly(count: int) -> None:
    values = _distinct_floats(count, 8)
    reference: list[Any] = [[_cell(v)] for v in values]
    candidate: list[Any] = [[_cell(v + 0.5)] for v in values]
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    started = time.perf_counter()
    assert not compare_results(_result(reference, 1), _result(candidate, 1), policy=policy).matches
    assert time.perf_counter() - started < 2.0
