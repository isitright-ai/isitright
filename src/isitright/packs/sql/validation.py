"""Contracts for trusted, programmatic candidate-state validators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from isitright.packs.sql.models import CanonicalValue, ContractModel


class ValidatorStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    INDETERMINATE = "INDETERMINATE"


class ValidationFinding(ContractModel):
    rule_id: str
    message: str
    location: str | None = None


class ValidatorResult(ContractModel):
    validator_name: str
    status: ValidatorStatus
    checked_rules: list[str] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)


@runtime_checkable
class CandidateStateView(Protocol):
    """Read-only, engine-neutral view exposed to trusted validators."""

    @property
    def engine(self) -> str: ...

    def table_names(self) -> Sequence[str]: ...

    def rows(self, table: str) -> Iterable[Mapping[str, CanonicalValue]]: ...


@runtime_checkable
class CandidateStateValidator(Protocol):
    """Trusted local callback; never loaded from a constraints document."""

    @property
    def name(self) -> str: ...

    def __call__(self, state: CandidateStateView) -> ValidatorResult: ...
