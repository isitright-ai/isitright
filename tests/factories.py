"""Small constructors for report-contract tests."""

from typing import Any

from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    OracleRecord,
    SearchRecord,
    ValidityRecord,
    totals_of,
)


def make_case(
    case_id: str,
    status: DivergenceStatus,
    tiers: tuple[str, ...] = ("STRUCTURAL",),
    **updates: Any,
) -> CaseReport:
    """A minimal valid case; counterexample statuses get one finding."""
    validity = ValidityRecord(status="VALID" if tiers else "NOT_ASSESSED", tiers=list(tiers))
    fidelity = FidelityRecord(found_on="NATIVE_ISOLATED", engine="sqlite 3")
    oracle = OracleRecord(name="reference_sql", kind="REFERENCE_PROGRAM")
    findings = (
        [
            Finding(
                finding_id=f"{case_id}:1",
                world_id="w",
                validity=validity,
                oracles=[oracle],
                fidelity=fidelity,
                headline="Evidence recorded for review",
            )
        ]
        if status is DivergenceStatus.COUNTEREXAMPLE_FOUND
        else []
    )
    fields: dict[str, Any] = {
        "case_id": case_id,
        "pack": "sql",
        "subject_kind": "ARTIFACT",
        "divergence_status": status,
        "validity": validity,
        "execution_fidelity": fidelity,
        "oracles": [oracle],
        "search": SearchRecord(seed=0, attempts=0, valid_candidates=0, executed=0),
        "findings": findings,
        "headline": "Evidence recorded for review",
        "elapsed_seconds": 0.0,
    }
    fields.update(updates)
    return CaseReport(**fields)


def make_audit(*cases: CaseReport) -> AuditReport:
    return AuditReport(
        pack="sql",
        kind="suite",
        cases=list(cases),
        totals=totals_of(list(cases)),
        elapsed_seconds=0.0,
    )
