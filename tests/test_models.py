from typing import Any

import pytest
from pydantic import ValidationError

from isitright.core.constraints import ValidityStatus, ValidityTier
from isitright.core.evidence import AttributionStatus, DivergenceStatus, FailOn
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    CheckConfig,
    ColumnComparisonPolicy,
    EffectiveOrdering,
    FloatComparisonMode,
    OrderingPolicy,
)
from isitright.packs.sql.reports import ReportFormat
from tests.factories import make_case


def test_enum_wire_values_are_locked() -> None:
    assert [item.value for item in DivergenceStatus] == [
        "COUNTEREXAMPLE_FOUND",
        "NOT_FOUND_WITHIN_BUDGET",
        "INCONCLUSIVE",
        "UNSUPPORTED",
    ]
    assert [item.value for item in ValidityTier] == [
        "STRUCTURAL",
        "DOMAIN_VALIDATED",
        "REACHABLE",
        "TASK_CONSISTENT",
        "OBSERVABLE",
        "SIMULATOR_CONSISTENT",
    ]
    assert [item.value for item in ValidityStatus] == [
        "VALID",
        "INVALID",
        "INDETERMINATE",
        "NOT_ASSESSED",
    ]
    assert [item.value for item in AttributionStatus] == [
        "UNDETERMINED",
        "AGENT_DEFECT",
        "REFERENCE_DEFECT",
        "AMBIGUOUS_TASK",
        "POLICY_AMBIGUOUS",
        "TOOL_CONTRACT_AMBIGUOUS",
        "SIMULATOR_DEFECT",
    ]
    assert [item.value for item in ColumnComparisonPolicy] == [
        "positional",
        "by_name",
        "names_and_positions",
    ]
    assert [item.value for item in OrderingPolicy] == ["auto", "ordered", "unordered"]
    assert [item.value for item in EffectiveOrdering] == ["ordered", "unordered"]
    assert [item.value for item in FailOn] == [
        "none",
        "domain-counterexample",
        "any-counterexample",
    ]
    assert [item.value for item in FloatComparisonMode] == ["exact", "isclose"]
    assert [item.value for item in ReportFormat] == ["json", "markdown", "both"]


def test_check_config_defaults_are_locked() -> None:
    assert CheckConfig().model_dump(mode="json") == {
        "seed": 0,
        "max_attempts": 500,
        "timeout_seconds": 30.0,
        "max_result_rows": 10000,
        "minimization_max_attempts": 500,
        "column_policy": "positional",
        "ordering_policy": "auto",
        "float_mode": "isclose",
        "float_relative_tolerance": 1e-9,
        "float_absolute_tolerance": 1e-12,
    }


@pytest.mark.parametrize(
    ("kind", "value", "engine_type"),
    [
        (CanonicalValueKind.NULL, None, None),
        (CanonicalValueKind.BOOLEAN, True, None),
        (CanonicalValueKind.INTEGER, 1, "INTEGER"),
        (CanonicalValueKind.DECIMAL, "1.00", "NUMERIC"),
        (CanonicalValueKind.FLOAT, 1.0, "REAL"),
        (CanonicalValueKind.TEXT, "1", "TEXT"),
        (CanonicalValueKind.BINARY, "AQI=", "BLOB"),
        (CanonicalValueKind.DATE, "2026-01-02", None),
        (CanonicalValueKind.TIME, "03:04:05", None),
        (CanonicalValueKind.DATETIME, "2026-01-02T03:04:05Z", None),
        (CanonicalValueKind.JSON, {"key": [1, True]}, None),
        (CanonicalValueKind.ENGINE_SPECIFIC, "opaque", "GEOGRAPHY"),
    ],
)
def test_canonical_values_retain_kind_and_native_diagnostics(
    kind: CanonicalValueKind, value: Any, engine_type: str | None
) -> None:
    result = CanonicalValue(kind=kind, value=value, engine_type=engine_type)
    assert result.value == value
    assert result.engine_type == engine_type


def test_canonical_integer_does_not_accept_boolean() -> None:
    with pytest.raises(ValidationError):
        CanonicalValue(kind=CanonicalValueKind.INTEGER, value=True)


def test_engine_specific_value_requires_native_type() -> None:
    with pytest.raises(ValidationError):
        CanonicalValue(kind=CanonicalValueKind.ENGINE_SPECIFIC, value="opaque")


@pytest.mark.parametrize("word", ["pass", "FAIL", "correct", "Wrong"])
def test_headline_rejects_verdict_vocabulary(word: str) -> None:
    with pytest.raises(ValidationError, match="never says pass, fail, correct or wrong"):
        make_case("q1", DivergenceStatus.INCONCLUSIVE, (), headline=f"This is {word}")
