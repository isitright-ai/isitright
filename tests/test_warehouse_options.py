"""Benchmark-style comparison options, question hints and the wall-time cap."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import CheckConfig, check
from isitright.packs.sql.comparison import ComparisonError, compare_results
from isitright.packs.sql.hints import question_literals
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ColumnComparisonPolicy,
    ComparisonPolicy,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)


def _int(v: int | None) -> CanonicalValue:
    if v is None:
        return CanonicalValue(kind=CanonicalValueKind.NULL, value=None)
    return CanonicalValue(kind=CanonicalValueKind.INTEGER, value=v)


def _float(v: float) -> CanonicalValue:
    return CanonicalValue(kind=CanonicalValueKind.FLOAT, value=v)


def _result(columns: list[str], rows: list[list[CanonicalValue]]) -> QueryResult:
    return QueryResult(columns=[ResultColumn(name=c) for c in columns], rows=rows)


def _policy(**kwargs: Any) -> ComparisonPolicy:
    return ComparisonPolicy(ordering=OrderingPolicy.UNORDERED, **kwargs)


def test_reference_columns_name_which_gold_columns_must_be_found() -> None:
    gold = _result(["a", "b"], [[_int(1), _int(10)], [_int(2), _int(20)]])
    candidate = _result(["x"], [[_int(2)], [_int(1)]])
    only_a = _policy(columns=ColumnComparisonPolicy.CONTAINED, reference_columns=[0])
    only_b = _policy(columns=ColumnComparisonPolicy.CONTAINED, reference_columns=[1])
    assert compare_results(gold, candidate, policy=only_a).matches
    outcome = compare_results(gold, candidate, policy=only_b)
    assert not outcome.matches and "b" in (outcome.difference or "")
    with pytest.raises(ComparisonError):
        compare_results(gold, candidate, policy=_policy(reference_columns=[5]))


def test_contained_columns_compare_each_column_on_its_own_and_ignore_extra_columns() -> None:
    gold = _result(["a", "b"], [[_int(1), _int(10)], [_int(2), _int(20)]])
    shuffled = _result(
        ["b", "a", "c"], [[_int(20), _int(1), _int(0)], [_int(10), _int(2), _int(0)]]
    )
    assert not compare_results(gold, shuffled, policy=_policy()).matches
    contained = _policy(columns=ColumnComparisonPolicy.CONTAINED)
    assert compare_results(gold, shuffled, policy=contained).matches
    # an ordered comparison keeps the order inside each column
    ordered = ComparisonPolicy(
        columns=ColumnComparisonPolicy.CONTAINED, ordering=OrderingPolicy.ORDERED
    )
    assert not compare_results(gold, shuffled, policy=ordered).matches


def test_null_as_zero_and_the_absolute_tolerance() -> None:
    gold = _result(["v"], [[_int(None)], [_float(1.0)]])
    candidate = _result(["v"], [[_int(0)], [_float(1.009)]])
    strict = _policy(columns=ColumnComparisonPolicy.CONTAINED)
    assert not compare_results(gold, candidate, policy=strict).matches
    zero = _policy(columns=ColumnComparisonPolicy.CONTAINED, null_as_zero=True)
    assert not compare_results(gold, candidate, policy=zero).matches  # 1.009 is off by 0.009
    loose = _policy(
        columns=ColumnComparisonPolicy.CONTAINED, null_as_zero=True, float_absolute_tolerance=0.01
    )
    assert compare_results(gold, candidate, policy=loose).matches


def test_the_options_are_recorded_in_the_report() -> None:
    report = check(
        reference_sql="SELECT a FROM t",
        candidate_sql="SELECT a, b FROM t",
        dialect="presto",
        ddl="CREATE TABLE t (a bigint, b bigint)",
        config=CheckConfig(
            max_attempts=20,
            column_policy=ColumnComparisonPolicy.CONTAINED,
            null_as_zero=True,
            reference_columns=[0],
            float_absolute_tolerance=0.01,
            ordering_policy=OrderingPolicy.UNORDERED,
        ),
    )
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    policy = report.comparison_policy
    assert policy["columns"] == "contained" and policy["null_as_zero"] is True
    assert policy["reference_columns"] == [0] and policy["float_absolute_tolerance"] == 0.01


def test_question_literals_are_numbers_quoted_strings_and_iso_dates_in_order() -> None:
    text = "How many orders over 100 in 'Texas' on 2021-01-07, excluding 'Nevada' and 2.5?"
    assert question_literals(text) == [100, "Texas", "2021-01-07", "Nevada", 2.5]
    assert question_literals("no constants here") == []
    assert len(question_literals(" ".join(str(n) for n in range(40)))) == 8


def test_the_question_adds_literal_hints_with_their_own_provenance() -> None:
    report = check(
        reference_sql="SELECT COUNT(*) FROM t WHERE qty > 5",
        candidate_sql="SELECT COUNT(*) FROM t WHERE qty >= 5",
        dialect="bigquery",
        ddl="CREATE TABLE d.t (qty INT64, name STRING)",
        question="How many rows have a quantity above 42?",
        config=CheckConfig(max_attempts=30),
    )
    used = report.search.hints_used
    assert any(name.startswith("question-literal:t.qty=42") for name in used), used


def test_the_wall_time_cap_stops_the_search_and_the_headline_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = itertools.count(step=0.4)
    monkeypatch.setattr("isitright.core.stochastic.time.monotonic", lambda: next(clock))
    report = check(
        reference_sql="SELECT a FROM t",
        candidate_sql="SELECT a FROM t",
        dialect="presto",
        ddl="CREATE TABLE t (a bigint, b varchar)",
        config=CheckConfig(max_attempts=500, wall_time_seconds=1.0),
    )
    assert report.search.budget["stopped_by"] == "seconds"
    assert "stopped by the time cap" in report.headline
    assert report.divergence_status in (
        DivergenceStatus.NOT_FOUND_WITHIN_BUDGET,
        DivergenceStatus.INCONCLUSIVE,
    )


def test_vector_comparison_reads_text_that_looks_like_a_number_as_a_number() -> None:
    # The benchmark writes both results to CSV and reads them back, so the text "2012" and the
    # integer 2012 are one value there (found on bq403: year as text against year as integer).
    def text(v: str) -> CanonicalValue:
        return CanonicalValue(kind=CanonicalValueKind.TEXT, value=v)

    def date(v: str) -> CanonicalValue:
        return CanonicalValue(kind=CanonicalValueKind.DATE, value=v)

    policy = _policy(columns=ColumnComparisonPolicy.CONTAINED)
    gold = _result(["year", "d"], [[text("2012"), _float(1.5)], [text("2013"), _float(2.5)]])
    candidate = _result(["y", "n"], [[_int(2013), _float(2.5)], [_int(2012), _float(1.5)]])
    assert compare_results(gold, candidate, policy=policy).matches
    # text that is not a plain number stays text
    words = _result(["w"], [[text("2012a")]])
    assert not compare_results(words, _result(["w"], [[_int(2012)]]), policy=policy).matches
    # a date equals its text
    dates = _result(["m"], [[date("2022-01-01")]])
    assert compare_results(dates, _result(["m"], [[text("2022-01-01")]]), policy=policy).matches
