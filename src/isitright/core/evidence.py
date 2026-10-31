"""Evidence: the one report schema (0.5; 0.4 reports still load), headlines, suite ranking, export.

Disagreement, validity, execution fidelity, oracle basis, stability and attribution are separate
fields. A headline is derived from them and never says pass, fail, correct or wrong.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from isitright.core.stochastic import Stability

SCHEMA_VERSION: Literal["0.5"] = "0.5"
_BANNED = re.compile(r"\b(pass|passed|fail|failed|failure|correct|incorrect|wrong)\b", re.I)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DivergenceStatus(StrEnum):
    COUNTEREXAMPLE_FOUND = "COUNTEREXAMPLE_FOUND"
    NOT_FOUND_WITHIN_BUDGET = "NOT_FOUND_WITHIN_BUDGET"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED = "UNSUPPORTED"


class AttributionStatus(StrEnum):
    UNDETERMINED = "UNDETERMINED"
    AGENT_DEFECT = "AGENT_DEFECT"
    REFERENCE_DEFECT = "REFERENCE_DEFECT"
    AMBIGUOUS_TASK = "AMBIGUOUS_TASK"
    POLICY_AMBIGUOUS = "POLICY_AMBIGUOUS"
    TOOL_CONTRACT_AMBIGUOUS = "TOOL_CONTRACT_AMBIGUOUS"
    SIMULATOR_DEFECT = "SIMULATOR_DEFECT"


class FailOn(StrEnum):
    NONE = "none"
    DOMAIN_COUNTEREXAMPLE = "domain-counterexample"
    ANY_COUNTEREXAMPLE = "any-counterexample"


class ValidityRecord(Closed):
    """Tiers reached, plus INVALID, INDETERMINATE or NOT_ASSESSED. Never merged with the rest."""

    status: Literal["VALID", "INVALID", "INDETERMINATE", "NOT_ASSESSED"]
    tiers: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    unobservable: bool = False
    """Every field the mutation changed is hidden from the agent: a tool-contract finding."""
    notes: list[str] = Field(default_factory=list)
    """Why a tier was withheld (for example a JSON field edited with no rule over its content)."""


class VerificationRecord(Closed):
    """What happened when an emulated finding was re-executed on the native engine."""

    status: Literal["VERIFIED", "EMULATION_ARTIFACT", "NOT_VERIFIED"]
    engine: str | None = None
    note: str = ""


class FidelityRecord(Closed):
    found_on: str
    verified_on: str | None = None
    engine: str | None = None
    verification: VerificationRecord | None = None


class OracleRecord(Closed):
    name: str
    kind: str
    outcome: Literal["MET", "NOT_MET", "CANNOT_JUDGE"] | None = None
    description: str = ""
    limits: list[str] = Field(default_factory=list)


class MutationRecord(Closed):
    family: str
    target: str
    description: str
    hints: list[str] = Field(default_factory=list)
    atoms: list[list[Any]] = Field(default_factory=list)


class ReplayRecord(Closed):
    command: str | None = None
    artifact: str | None = None
    artifact_sha256: str | None = None


class ScreeningRecord(Closed):
    """Screening without the agent: a ranking input, never a verdict."""

    screening_class: Literal["WRONG_IF_UNCHANGED", "STALE", "RIGHT_IF_UNCHANGED", "UNSCREENABLE"]
    basis: str = ""
    rank: int | None = None


class ScreeningSummary(Closed):
    ranking: str
    """How worlds were ordered: ``screening``, ``coverage`` or ``random``."""
    baseline_trace: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""


class StratumRecord(Closed):
    family: str
    target: str
    role: str
    worlds_total: int
    worlds_run: int
    worlds_not_run: int
    with_findings: int
    stopped: bool
    stop_reason: str | None = None
    summary: str = ""
    """For example "no finding in 8 of 40 worlds: stratum rule (8 worlds without a finding)"."""


class StoppingRecord(Closed):
    stratum_patience: int | None = None
    run_patience: int | None = None
    run_stop_reason: str | None = None
    strata: list[StratumRecord] = Field(default_factory=list)


class HintUse(Closed):
    name: str
    kind: str
    provenance: str
    worlds: list[str] = Field(default_factory=list)
    """Worlds that a hint led to (generated from a mutation carrying the hint)."""


class SearchRecord(Closed):
    seed: int
    attempts: int
    valid_candidates: int
    executed: int
    rejected: dict[str, int] = Field(default_factory=dict)
    families_run: list[str] = Field(default_factory=list)
    families_skipped: dict[str, str] = Field(default_factory=dict)
    budget_by_group: dict[str, dict[str, int]] = Field(default_factory=dict)
    hints_used: list[str] = Field(default_factory=list)
    depth_reached: int = 0
    notes: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    screening: ScreeningSummary | None = None
    stopping: StoppingRecord | None = None
    hint_use: list[HintUse] = Field(default_factory=list)


class Finding(Closed):
    """One disagreement in one world; attribution is separate and undetermined by default."""

    finding_id: str
    world_id: str
    validity: ValidityRecord
    oracles: list[OracleRecord]
    stability: Stability | None = None
    world_diff: dict[str, Any] = Field(default_factory=dict)
    mutation_path: list[MutationRecord] = Field(default_factory=list)
    divergence: dict[str, Any] = Field(default_factory=dict)
    fidelity: FidelityRecord
    replay: ReplayRecord = Field(default_factory=ReplayRecord)
    export: str | None = None
    minimization: dict[str, Any] = Field(default_factory=dict)
    headline: str

    @field_validator("headline")
    @classmethod
    def headline_avoids_verdicts(cls, value: str) -> str:
        return _check_headline(value)


class WorldRecord(Closed):
    id: str
    role: str
    description: str
    validity: ValidityRecord
    oracle_outcome: Literal["MET", "NOT_MET", "CANNOT_JUDGE"] | None = None
    role_basis: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    mutation_path: list[MutationRecord] = Field(default_factory=list)
    screening: ScreeningRecord | None = None
    run_status: Literal["RUN", "NOT_RUN"] = "RUN"
    not_run_reason: str | None = None
    """A world that was not run is reported as not run, never as passing."""


class ControlsRecord(Closed):
    status: Literal["DISCRIMINATING", "NOT_DISCRIMINATING", "NOT_APPLICABLE"]
    detail: str


class CaseReport(Closed):
    case_id: str
    pack: str
    task: str | None = None
    subject_kind: Literal["ARTIFACT", "FROZEN_ARTIFACT", "AGENT"]
    divergence_status: DivergenceStatus
    validity: ValidityRecord
    execution_fidelity: FidelityRecord
    oracles: list[OracleRecord]
    stability: Stability | None = None
    attribution_status: AttributionStatus = AttributionStatus.UNDETERMINED
    search: SearchRecord
    findings: list[Finding] = Field(default_factory=list)
    worlds: list[WorldRecord] = Field(default_factory=list)
    controls: ControlsRecord | None = None
    comparison_policy: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    original_state: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    checked_rules: list[str] = Field(default_factory=list)
    unused_rules: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    headline: str
    elapsed_seconds: float = Field(ge=0)
    extensions: dict[str, Any] = Field(default_factory=dict)
    """Pack-specific fields (SQL results, MCP run records). Not part of the common contract."""

    @field_validator("headline")
    @classmethod
    def headline_avoids_verdicts(cls, value: str) -> str:
        return _check_headline(value)

    @model_validator(mode="after")
    def status_matches_findings(self) -> Self:
        if (self.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND) != bool(self.findings):
            raise ValueError("counterexample status and findings must agree")
        if self.divergence_status is DivergenceStatus.UNSUPPORTED and self.search.executed:
            raise ValueError("an unsupported case has no executed worlds")
        engine = (self.execution_fidelity.engine or "").split(" ")[0]
        if engine == "duckdb" and self.execution_fidelity.found_on != "EMULATED":
            raise ValueError("DuckDB results must be labeled EMULATED")
        if engine in {"postgres", "sqlite"} and self.execution_fidelity.found_on == "EMULATED":
            raise ValueError(f"{engine} results are native, not EMULATED")
        return self


class Totals(Closed):
    cases: int = Field(ge=0)
    by_divergence_status: dict[str, int] = Field(default_factory=dict)
    by_validity: dict[str, int] = Field(default_factory=dict)
    by_family: dict[str, int] = Field(default_factory=dict)


class AuditReport(Closed):
    """The report of one audit: a single check, a suite, or an agent scenario."""

    schema_version: Literal["0.4", "0.5"] = SCHEMA_VERSION
    """0.4 reports stay readable: every field added in 0.5 is optional."""
    pack: str
    kind: Literal["case", "suite", "scenario"]
    cases: list[CaseReport]
    totals: Totals
    elapsed_seconds: float = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def ranked(self) -> list[CaseReport]:
        return rank_cases(self.cases)


def safe_detail(text: object) -> str:
    """Error text for a headline, or a pointer to the errors list if it uses verdict words."""
    value = " ".join(str(text).split())
    return "see the errors list" if _BANNED.search(value) else value


def _check_headline(value: str) -> str:
    if _BANNED.search(value):
        raise ValueError("a headline never says pass, fail, correct or wrong")
    return value


def evidence_strength(case: CaseReport) -> int:
    """0 is strongest: domain-validated counterexamples, then structural-only, then the rest."""
    if case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND:
        tiers = set(case.validity.tiers)
        if "DOMAIN_VALIDATED" in tiers:
            return 0
        if "STRUCTURAL" in tiers:
            return 1
    if case.divergence_status in {DivergenceStatus.INCONCLUSIVE, DivergenceStatus.UNSUPPORTED}:
        return 2
    if case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET:
        return 3
    return 2


def rank_cases(cases: list[CaseReport]) -> list[CaseReport]:
    return sorted(cases, key=evidence_strength)


def totals_of(cases: list[CaseReport]) -> Totals:
    by_status: dict[str, int] = {}
    by_validity: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for case in cases:
        by_status[case.divergence_status.value] = by_status.get(case.divergence_status.value, 0) + 1
        label: str = (
            "DOMAIN_VALIDATED"
            if "DOMAIN_VALIDATED" in case.validity.tiers
            else case.validity.status
        )
        if "DOMAIN_VALIDATED" not in case.validity.tiers and "STRUCTURAL" in case.validity.tiers:
            label = "STRUCTURAL"
        by_validity[label] = by_validity.get(label, 0) + 1
        for finding in case.findings:
            if finding.mutation_path:
                family = finding.mutation_path[-1].family
                by_family[family] = by_family.get(family, 0) + 1
    return Totals(
        cases=len(cases),
        by_divergence_status=dict(sorted(by_status.items())),
        by_validity=dict(sorted(by_validity.items())),
        by_family=dict(sorted(by_family.items())),
    )


def policy_triggered(case: CaseReport, policy: FailOn) -> bool:
    """CI policy. An emulated, natively unverified finding never fails CI by default."""
    if policy is FailOn.NONE or case.divergence_status is not DivergenceStatus.COUNTEREXAMPLE_FOUND:
        return False
    if case.execution_fidelity.found_on == "EMULATED" and not case.execution_fidelity.verified_on:
        return False
    if policy is FailOn.ANY_COUNTEREXAMPLE:
        return True
    return "DOMAIN_VALIDATED" in case.validity.tiers


def headline_for(case_status: DivergenceStatus, summary: str) -> str:
    """Prefix a pack's evidence summary with the status; the summary must avoid verdict words."""
    return _check_headline(f"{case_status.value.replace('_', ' ').capitalize()}: {summary}")


class EvalCase(Closed):
    """A counterexample exported as a new eval case in the pack's format."""

    pack: str
    case_id: str
    source_finding: str
    payload: dict[str, Any]
    expectation: dict[str, Any]
