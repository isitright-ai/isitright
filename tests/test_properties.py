from hypothesis import given, settings
from hypothesis import strategies as st

from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)


def _integer_result(values: list[int]) -> QueryResult:
    return QueryResult(
        columns=[ResultColumn(name="value")],
        rows=[[CanonicalValue(kind=CanonicalValueKind.INTEGER, value=value)] for value in values],
    )


@given(st.lists(st.integers(min_value=-(2**63), max_value=2**63 - 1), max_size=40))
@settings(deadline=None)
def test_unordered_comparison_is_invariant_under_reversal(values: list[int]) -> None:
    reference = _integer_result(values)
    candidate = _integer_result(list(reversed(values)))

    outcome = compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(ordering=OrderingPolicy.UNORDERED),
    )

    assert outcome.matches


@given(
    st.lists(st.integers(min_value=-1000, max_value=1000), max_size=30),
    st.integers(min_value=-1000, max_value=1000),
)
@settings(deadline=None)
def test_unordered_comparison_preserves_duplicate_multiplicity(
    values: list[int], extra: int
) -> None:
    reference = _integer_result(values)
    candidate = _integer_result([*values, extra])

    outcome = compare_results(
        reference,
        candidate,
        policy=ComparisonPolicy(ordering=OrderingPolicy.UNORDERED),
    )

    assert not outcome.matches


@given(st.lists(st.integers(), max_size=40))
@settings(deadline=None)
def test_ordered_comparison_is_reflexive(values: list[int]) -> None:
    result = _integer_result(values)
    outcome = compare_results(
        result,
        result,
        policy=ComparisonPolicy(ordering=OrderingPolicy.ORDERED),
    )
    assert outcome.matches
