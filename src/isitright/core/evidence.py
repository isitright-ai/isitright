"""Evidence: the one report schema (0.5; 0.4 reports still load), headlines, suite ranking, export.

Disagreement, validity, execution fidelity, oracle basis, stability and attribution are separate
fields. A headline is derived from them and never says pass, fail, correct or wrong.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from isitright.core.sequential import Decision
from isitright.core.stochastic import EvidenceGrade as EvidenceGrade
from isitright.core.stochastic import Multiplicity, Observation, Stability

SCHEMA_VERSION: Literal["0.9"] = "0.9"
_BANNED = re.compile(r"\b(pass|passed|fail|failed|failure|correct|incorrect|wrong)\b", re.I)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DivergenceStatus(StrEnum):
    COUNTEREXAMPLE_FOUND = "COUNTEREXAMPLE_FOUND"
    OBSERVED_FAILURE = "OBSERVED_FAILURE"
    """Live agents only: a judged run failed on a mutated world that ran and was not found invalid
    (the validity of each world is stated apart: it may be NOT_ASSESSED), and no paired test decided
    a higher failure rate. Weaker than COUNTEREXAMPLE_FOUND, and stronger than finding nothing."""
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


class LiveFailOn(StrEnum):
    """`FailOn` for the commands that run a live agent (research): two more policies."""

    NONE = "none"
    DOMAIN_COUNTEREXAMPLE = "domain-counterexample"
    ANY_COUNTEREXAMPLE = "any-counterexample"
    RATE_INCREASE = "rate-increase"
    """Only a finding whose paired test decided a higher failure rate. The same as
    ``any-counterexample``, which no observed failure ever triggers."""
    OBSERVED_FAILURE = "observed-failure"
    """Also a failure observed on a world that ran and was not found invalid, with no rate
    decision."""


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
    """Worlds that a hint led to (the first ones; ``world_count`` has the total)."""
    world_count: int = 0


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


class LiveRecord(Closed):
    """What the agent itself did on a world, kept apart from the frozen program that found it.

    A frozen finding is scoped to a recorded program. A live record says the agent was run, how
    many times, and whether its own code changed: the evidence about the agent.
    """

    status: Literal["CONFIRMED", "NOT_CONFIRMED", "INCONCLUSIVE"]
    runs: int = Field(ge=0)
    baseline_runs: int = Field(ge=0)
    not_met: int = Field(ge=0)
    agent_runs_only: bool = True
    """Every run counted here was made by the agent under test, not replayed from a recording."""
    program_changed_runs: int = Field(ge=0)
    """Runs where the agent wrote code unlike its baseline code."""
    found_by_frozen_replay: bool = False
    """The frozen program already disagreed with the reference on this world (``found_on``)."""
    note: str = ""


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
    evidence_grade: EvidenceGrade | None = None
    """Added in 0.9 for the findings of live stochastic agents: ``RATE_INCREASE`` (a paired
    sequential test decided a higher failure rate) or ``OBSERVED_FAILURE`` (a judged run failed on a
    world that was not found invalid, nothing more). Neither says the world was validated: that is
    the finding's own ``validity`` (``NOT_ASSESSED`` for a fixed world without a validator).
    ``None``: the finding is not a rate statement (a frozen program or report, a deterministic
    subject, SQL)."""
    observation: Observation | None = None
    """Added in 0.9: failures / judged runs on the shown world (and on the baseline runs made for
    its pairs), errors and unjudged runs beside them, with Wilson intervals."""
    mode: Literal["frozen_program", "frozen_trace", "live_agent"] | None = None
    """Added in 0.6. ``frozen_program``: a recorded program on a world. ``frozen_trace`` (0.8): a
    recorded run replayed, its report not regenerated. ``live_agent``: the agent's own runs.
    ``None``: not stated (0.4 and 0.5 reports, and packs without the distinction)."""
    live: LiveRecord | None = None
    headline: str

    @field_validator("headline")
    @classmethod
    def headline_avoids_verdicts(cls, value: str) -> str:
        return _check_headline(value)

    @model_validator(mode="after")
    def grade_matches_its_evidence(self) -> Self:
        """A finding cannot claim a higher grade than the runs behind it support."""
        grade = self.evidence_grade
        if grade is None:
            return self  # frozen, deterministic, SQL and legacy findings carry no grade
        sequential = self.stability.sequential if self.stability else None
        claim = self.stability.rate_claim if self.stability else None
        if grade is EvidenceGrade.RATE_INCREASE:
            if sequential is None or sequential.decision is not Decision.RATE_INCREASE:
                raise ValueError("a rate increase needs a sequential decision of RATE_INCREASE")
            if claim is None:
                raise ValueError("a rate increase needs the rate claim of its sequential test")
            if (
                claim.test != sequential.test
                or claim.paired_runs != sequential.pairs
                or claim.discordant_world_only != sequential.discordant_world_only
                or claim.discordant_baseline_only != sequential.discordant_baseline_only
                or claim.p_value != sequential.p_value
                or claim.alpha != sequential.alpha
            ):
                raise ValueError("the rate claim and the sequential record disagree")
            return self
        if sequential is not None and sequential.decision is Decision.RATE_INCREASE:
            raise ValueError("an observed failure cannot carry a decided rate increase")
        if claim is not None:
            raise ValueError("an observed failure carries no rate claim")
        if self.observation is None or self.observation.world.failures < 1:
            raise ValueError("an observed failure needs at least one judged failure recorded")
        return self


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
    multiplicity: Multiplicity | None = None
    """Added in 0.9, live agents: how many worlds were tested and what that means for the claims."""
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
        strong = [
            f for f in self.findings if f.evidence_grade is not EvidenceGrade.OBSERVED_FAILURE
        ]
        if (self.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND) != bool(strong):
            raise ValueError("counterexample status and findings must agree")
        if (self.divergence_status is DivergenceStatus.OBSERVED_FAILURE) != (
            bool(self.findings) and not strong
        ):
            raise ValueError("observed-failure status holds exactly when every finding is one")
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

    schema_version: Literal["0.4", "0.5", "0.6", "0.8", "0.9"] = SCHEMA_VERSION
    """0.4 and 0.5 reports stay readable: every field added since is optional."""
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


def safe_name(name: object, what: str) -> str:
    """A name the user chose (a world id, an invariant name) for a headline.

    A name that uses a verdict word would make the report model refuse the headline. It is replaced
    by a pointer, and the report keeps the name in full where it is data (``world_id``, the
    violations list).
    """
    value = " ".join(str(name).split())
    return f"({what} in the report)" if _BANNED.search(value) else value


def _check_headline(value: str) -> str:
    if _BANNED.search(value):
        raise ValueError("a headline never says pass, fail, correct or wrong")
    return value


def evidence_strength(case: CaseReport) -> int:
    """0 is strongest. Domain-validated counterexamples, structurally validated ones, other
    counterexamples (an unassessed validity included), observed failures, inconclusive and
    unsupported cases, then cases where nothing was found. Equal strengths keep their order."""
    status = case.divergence_status
    if status is DivergenceStatus.COUNTEREXAMPLE_FOUND:
        tiers = set(case.validity.tiers)
        if "DOMAIN_VALIDATED" in tiers:
            return 0
        if "STRUCTURAL" in tiers:
            return 1
        return 2
    if status is DivergenceStatus.OBSERVED_FAILURE:
        return 3
    if status in {DivergenceStatus.INCONCLUSIVE, DivergenceStatus.UNSUPPORTED}:
        return 4
    return 5


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


def policy_triggered(case: CaseReport, policy: FailOn | LiveFailOn) -> bool:
    """CI policy. An emulated, natively unverified finding never fails CI by default."""
    if policy.value == "none":
        return False
    if case.divergence_status is DivergenceStatus.OBSERVED_FAILURE:
        return policy.value == "observed-failure"
    if case.divergence_status is not DivergenceStatus.COUNTEREXAMPLE_FOUND:
        return False
    if case.execution_fidelity.found_on == "EMULATED" and not case.execution_fidelity.verified_on:
        return False
    if policy.value in {"any-counterexample", "rate-increase", "observed-failure"}:
        return True
    return "DOMAIN_VALIDATED" in case.validity.tiers


def headline_for(case_status: DivergenceStatus, summary: str) -> str:
    """Prefix a pack's evidence summary with the status; the summary must avoid verdict words."""
    label = (
        "Observed disagreement"
        if case_status is DivergenceStatus.OBSERVED_FAILURE
        else case_status.value.replace("_", " ").capitalize()
    )
    return _check_headline(f"{label}: {summary}")


class EvalCase(Closed):
    """A counterexample exported as a new eval case in the pack's format."""

    pack: str
    case_id: str
    source_finding: str
    payload: dict[str, Any]
    expectation: dict[str, Any]


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _rate_text(rate: Any) -> str:
    """``3 of 5 judged runs (60%, 95% Wilson interval 23% to 88%), 1 errored, 0 not judged``."""
    text = f"{rate.failures} of {rate.judged} judged runs"
    if rate.judged:
        text += (
            f" ({_percent(rate.rate)}, 95% Wilson interval "
            f"{_percent(rate.interval_low)} to {_percent(rate.interval_high)})"
        )
    return f"{text}; {rate.errors} errored, {rate.unjudged} not judged"


def _validity_text(validity: ValidityRecord) -> str:
    """What was established about the world: tiers reached, or that nothing was assessed."""
    if validity.status == "NOT_ASSESSED":
        return (
            "NOT_ASSESSED (no validation was run on this world; it ran because nothing marked "
            "it invalid, and no validity tier is claimed)"
        )
    if validity.status == "VALID":
        return f"VALID ({', '.join(validity.tiers) or 'no tier reached'})"
    return validity.status


def describe_graded_findings(case: CaseReport) -> list[str]:
    """Markdown lines for the findings of a live-agent case, one section per grade.

    Observed failures are shown whenever they exist, with counts, whatever the paired test said. A
    rate increase is shown apart and is the only grade that supports a claim about the failure
    rate. Findings without a grade (frozen programs, SQL, deterministic subjects) are not listed.
    """
    by_grade = {
        grade: [f for f in case.findings if f.evidence_grade is grade] for grade in EvidenceGrade
    }
    lines: list[str] = []

    def entry(finding: Finding) -> str:
        text = f"- {finding.world_id}"
        if finding.observation is not None:
            text += f": {_rate_text(finding.observation.world)}"
            baseline = finding.observation.baseline
            if baseline is not None:
                text += f". Baseline runs made for its pairs: {_rate_text(baseline)}"
        if finding.mutation_path:
            text += ". World change: " + "; ".join(m.description for m in finding.mutation_path)
        sequential = finding.stability.sequential if finding.stability else None
        if sequential is not None:
            text += f". Paired test: {sequential.decision.value} after {sequential.pairs} pairs"
        graded_on = finding.divergence.get("graded_on_world")
        if graded_on and graded_on != finding.world_id:
            text += (
                f". The grade and the counts above describe the world the search ran "
                f"({graded_on}); "
                f"the world shown ({finding.world_id}) is its minimization and was not itself "
                "tested by the paired test (ledger E4: open until N5)"
            )
        text += f". World validity: {_validity_text(finding.validity)}"
        if finding.replay.command:
            text += f". Replay: `{finding.replay.command}`"
        return text + "."

    if by_grade[EvidenceGrade.RATE_INCREASE]:
        lines += ["", "## Rate increases", ""]
        lines.append(
            "A paired sequential test decided that the world fails more often than the baseline. "
            "This is the only grade that supports a claim about the failure rate. The claim is "
            "about the world as run: whether the world satisfies structural or domain "
            "requirements is the separate validity stated for each world."
        )
        lines += [entry(f) for f in by_grade[EvidenceGrade.RATE_INCREASE]]
    if by_grade[EvidenceGrade.OBSERVED_FAILURE]:
        lines += ["", "## Observed failures", ""]
        lines.append(
            "A judged run failed on a mutated world that ran and was not found invalid. This is "
            "actionable evidence: the world and a replay are below. Each entry states how far the "
            "world was validated (a world marked NOT_ASSESSED was not). It is not a statement "
            "that the mutation raises the agent's failure probability, because no paired test "
            "decided that. Intervals are descriptive."
        )
        lines += [entry(f) for f in by_grade[EvidenceGrade.OBSERVED_FAILURE]]
    if case.multiplicity is not None:
        m = case.multiplicity
        lines += [
            "",
            "## Worlds tested",
            "",
            f"{m.worlds_tested} worlds had a judged run: {m.worlds_with_observed_failure} with an "
            f"observed failure, {m.worlds_with_rate_increase} with a rate increase decided. "
            f"{m.note}",
        ]
        if m.expected_worlds_with_observed_failure_under_no_effect is not None:
            lines.append(
                f"If every world failed at the baseline's observed rate, about "
                f"{m.expected_worlds_with_observed_failure_under_no_effect:.1f} worlds would show "
                "an observed failure by chance."
            )
    return lines
