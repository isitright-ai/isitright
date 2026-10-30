"""Data contracts of the SQL pack: query results, comparison policy, suite inputs, check config."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContractModel(BaseModel):
    """Base class for closed, deterministic report contracts."""

    model_config = ConfigDict(extra="forbid")


class ColumnComparisonPolicy(StrEnum):
    POSITIONAL = "positional"
    BY_NAME = "by_name"
    NAMES_AND_POSITIONS = "names_and_positions"


class OrderingPolicy(StrEnum):
    AUTO = "auto"
    ORDERED = "ordered"
    UNORDERED = "unordered"


class EffectiveOrdering(StrEnum):
    ORDERED = "ordered"
    UNORDERED = "unordered"


class FloatComparisonMode(StrEnum):
    EXACT = "exact"
    ISCLOSE = "isclose"


class CanonicalValueKind(StrEnum):
    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    FLOAT = "float"
    TEXT = "text"
    BINARY = "binary"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    JSON = "json"
    ENGINE_SPECIFIC = "engine_specific"


class CheckConfig(ContractModel):
    """Deterministic controls shared by single-case and suite analysis."""

    seed: int = 0
    max_attempts: int = Field(default=500, ge=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_result_rows: int = Field(default=10_000, ge=1)
    minimization_max_attempts: int = Field(default=500, ge=0)
    column_policy: ColumnComparisonPolicy = ColumnComparisonPolicy.POSITIONAL
    ordering_policy: OrderingPolicy = OrderingPolicy.AUTO
    float_mode: FloatComparisonMode = FloatComparisonMode.ISCLOSE
    float_relative_tolerance: float = Field(default=1e-9, ge=0)
    float_absolute_tolerance: float = Field(default=1e-12, ge=0)


class SuiteCase(ContractModel):
    """One JSONL input record; unknown fields are retained as metadata."""

    case_id: str = Field(min_length=1)
    reference_sql: str = Field(min_length=1)
    candidate_sql: str = Field(min_length=1)
    question: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def collect_extra_metadata(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        known = {"case_id", "reference_sql", "candidate_sql", "question", "metadata"}
        result = dict(value)
        metadata = dict(result.get("metadata") or {})
        for key in list(result):
            if key not in known:
                metadata[key] = result.pop(key)
        result["metadata"] = metadata
        return result


class ComparisonPolicy(ContractModel):
    columns: ColumnComparisonPolicy = ColumnComparisonPolicy.POSITIONAL
    ordering: OrderingPolicy = OrderingPolicy.AUTO
    effective_ordering: EffectiveOrdering | None = None
    float_mode: FloatComparisonMode = FloatComparisonMode.ISCLOSE
    float_relative_tolerance: float = Field(default=1e-9, ge=0)
    float_absolute_tolerance: float = Field(default=1e-12, ge=0)
    unordered_rows_are_multiset: Literal[True] = True


class CanonicalValue(ContractModel):
    """An engine-neutral, JSON-safe query-result value.

    Decimal values use exact strings and binary values use base64 strings. The
    adapter may retain its native type name in ``engine_type`` for diagnostics.
    """

    kind: CanonicalValueKind
    value: JsonValue
    engine_type: str | None = None

    @model_validator(mode="after")
    def value_matches_kind(self) -> Self:
        value = self.value
        valid = {
            CanonicalValueKind.NULL: value is None,
            CanonicalValueKind.BOOLEAN: isinstance(value, bool),
            CanonicalValueKind.INTEGER: isinstance(value, int) and not isinstance(value, bool),
            CanonicalValueKind.DECIMAL: isinstance(value, str),
            CanonicalValueKind.FLOAT: isinstance(value, float),
            CanonicalValueKind.TEXT: isinstance(value, str),
            CanonicalValueKind.BINARY: isinstance(value, str),
            CanonicalValueKind.DATE: isinstance(value, str),
            CanonicalValueKind.TIME: isinstance(value, str),
            CanonicalValueKind.DATETIME: isinstance(value, str),
            CanonicalValueKind.JSON: True,
            CanonicalValueKind.ENGINE_SPECIFIC: self.engine_type is not None,
        }[self.kind]
        if not valid:
            raise ValueError(f"value does not match canonical kind {self.kind}")
        return self


class ResultColumn(ContractModel):
    name: str


class QueryResult(ContractModel):
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[list[CanonicalValue]] = Field(default_factory=list)
