"""H5: two crash paths.

X1: a world or an invariant named with a verdict word ("wrong-zip", "no-failure-allowed") made the
report model refuse the headline, so the whole agents report failed to build. Q4: the unordered row
comparison recursed once per row, so a large result with equal rows raised ``RecursionError``, and
its worst case was quadratic.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue

from isitright.core.evidence import safe_name
from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    FloatComparisonMode,
    OrderingPolicy,
    QueryResult,
    ResultColumn,
)

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"


def test_safe_name_keeps_a_clean_name_and_points_at_the_report_for_a_flagged_one() -> None:
    assert safe_name("refund_never_fails", "invariant name") == "refund_never_fails"
    assert safe_name("booked_24h_01m", "world id") == "booked_24h_01m"
    assert safe_name("wrong-zip", "world id") == "(world id in the report)"
    assert safe_name("no-failure-allowed", "invariant name") == "(invariant name in the report)"
    assert safe_name("  two   words\nhere ", "world id") == "two words here"


VARIANT = """
import dataclasses
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("booking_base_for_names", r"{base}")
module = importlib.util.module_from_spec(spec)
sys.modules["booking_base_for_names"] = module
spec.loader.exec_module(module)

base = module.SCENARIO
invariant = dataclasses.replace(base.oracle.invariants[0], name="{invariant}")
worlds = [
    dataclasses.replace(w, id="wrong-zip") if w.id == "booked_24h_01m" else w
    for w in base.fixed_worlds
]
SCENARIO = dataclasses.replace(
    base,
    fixed_worlds=worlds,
    oracle=dataclasses.replace(base.oracle, invariants=[invariant]),
)
"""


@pytest.mark.parametrize("invariant", ["refund_never_fails", "no-failure-allowed"])
def test_an_agents_report_builds_for_a_world_and_an_invariant_named_with_a_verdict_word(
    tmp_path: Path, invariant: str
) -> None:
    from isitright.packs.mcp.audit import run_scenario, write_report

    module = tmp_path / "variant_scenario.py"
    module.write_text(
        VARIANT.format(base=str(EXAMPLES / "booking_scenario.py"), invariant=invariant),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", "careless")
        report = run_scenario(
            scenario_ref=f"{module}:SCENARIO",
            agent_command=f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"',
            output_dir=out,
            worlds="fixed",
            k=1,
            only=["wrong-zip", "flight_cancelled"],
            trust_code=True,
            timeout_seconds=120,
        )
    write_report(report, out)
    case = report.cases[0]
    finding = next(f for f in case.findings if f.world_id == "wrong-zip")
    assert finding.divergence["violations"][0]["invariant"] == invariant  # kept in full
    assert "wrong-zip" not in finding.headline  # the headline points at the report instead
    assert "world id in the report" in finding.headline
    assert (out / "report.json").is_file() and (out / "report.md").is_file()


# -- Q4 --------------------------------------------------------------------------------------


def _value(kind: CanonicalValueKind, value: object) -> CanonicalValue:
    return CanonicalValue(kind=kind, value=cast(JsonValue, value))


def _result(rows: list[list[CanonicalValue]], width: int = 1) -> QueryResult:
    return QueryResult(columns=[ResultColumn(name=f"c{i}") for i in range(width)], rows=rows)


def _timed(reference: QueryResult, candidate: QueryResult, policy: ComparisonPolicy):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    outcome = compare_results(reference, candidate, policy=policy)
    return outcome, time.perf_counter() - started


@pytest.mark.parametrize(
    "policy",
    [
        ComparisonPolicy(ordering=OrderingPolicy.UNORDERED),
        ComparisonPolicy(ordering=OrderingPolicy.UNORDERED, float_mode=FloatComparisonMode.EXACT),
    ],
    ids=["tolerance", "exact"],
)
def test_100000_identical_rows_compare_in_under_two_seconds(policy: ComparisonPolicy) -> None:
    row = [
        _value(CanonicalValueKind.INTEGER, 7),
        _value(CanonicalValueKind.TEXT, "north"),
        _value(CanonicalValueKind.FLOAT, 2.5),
    ]
    reference = _result([row] * 100_000, width=3)
    candidate = _result([list(row) for _ in range(100_000)], width=3)
    outcome, seconds = _timed(reference, candidate, policy)
    assert outcome.matches is True
    assert seconds < 2.0, f"{seconds:.2f}s"


def test_100000_distinct_rows_without_floats_compare_in_under_two_seconds() -> None:
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    rows = [[_value(CanonicalValueKind.INTEGER, i)] for i in range(100_000)]
    outcome, seconds = _timed(_result(rows), _result(list(reversed(rows))), policy)
    assert outcome.matches is True
    assert seconds < 2.0, f"{seconds:.2f}s"
    changed = [*rows[:-1], [_value(CanonicalValueKind.INTEGER, -1)]]
    outcome, _ = _timed(_result(rows), _result(changed), policy)
    assert outcome.matches is False and outcome.difference == "unordered row multiset differs"


def test_thousands_of_equal_float_rows_do_not_exhaust_the_stack() -> None:
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    rows = [[_value(CanonicalValueKind.FLOAT, 1.5)] for _ in range(5_000)]
    assert compare_results(_result(rows), _result(list(rows)), policy=policy).matches is True


def test_tolerance_matching_still_finds_a_perfect_matching_a_greedy_pairing_misses() -> None:
    """100 is within tolerance of 91 and of 109, which are not within tolerance of each other:
    pairing the equal 100s first would leave 109 against 91. A matching exists."""
    policy = ComparisonPolicy(
        ordering=OrderingPolicy.UNORDERED,
        float_relative_tolerance=0.1,
        float_absolute_tolerance=0.0,
    )

    def column(*values: float) -> QueryResult:
        return _result([[_value(CanonicalValueKind.FLOAT, v)] for v in values])

    assert compare_results(column(100.0, 109.0), column(100.0, 91.0), policy=policy).matches
    assert not compare_results(column(100.0, 109.0), column(91.0, 91.0), policy=policy).matches
    assert not compare_results(column(100.0, 100.0), column(100.0, 1000.0), policy=policy).matches


def test_rows_that_differ_outside_their_float_cells_never_match_each_other() -> None:
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    flo = _value(CanonicalValueKind.FLOAT, 1.0)
    a, b = _value(CanonicalValueKind.TEXT, "a"), _value(CanonicalValueKind.TEXT, "b")
    assert compare_results(_result([[a, flo]], 2), _result([[a, flo]], 2), policy=policy).matches
    assert not compare_results(
        _result([[a, flo]], 2), _result([[b, flo]], 2), policy=policy
    ).matches


def test_decimals_that_are_numerically_equal_still_match_and_nan_never_does() -> None:
    policy = ComparisonPolicy(ordering=OrderingPolicy.UNORDERED)
    one = _value(CanonicalValueKind.DECIMAL, "1.0")
    one_more_digit = _value(CanonicalValueKind.DECIMAL, "1.00")
    assert compare_results(_result([[one]]), _result([[one_more_digit]]), policy=policy).matches
    nan = float("nan")
    rows = [[_value(CanonicalValueKind.FLOAT, nan)]]
    assert not compare_results(_result(rows), _result(list(rows)), policy=policy).matches
