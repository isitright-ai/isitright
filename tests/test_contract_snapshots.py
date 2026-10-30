import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from isitright.core.evidence import SCHEMA_VERSION, AuditReport, DivergenceStatus
from tests.factories import make_audit, make_case


def snapshot_path(name: str) -> Path:
    return Path("tests/snapshots") / name


def load_snapshot(name: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(snapshot_path(name).read_text(encoding="utf-8"))
    return value


def _case_audit() -> AuditReport:
    case = make_case(
        "snapshot-case",
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
        ("STRUCTURAL", "DOMAIN_VALIDATED"),
        headline="Evidence recorded for review",
    )
    return make_audit(case).model_copy(update={"kind": "case"})


def _suite_audit() -> AuditReport:
    return make_audit(
        make_case("a", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL", "DOMAIN_VALIDATED")),
        make_case("b", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ()),
        make_case("c", DivergenceStatus.UNSUPPORTED, ()),
    )


def test_report_serialization_snapshots() -> None:
    for name, report in (
        ("case_report.json", _case_audit()),
        ("suite_report.json", _suite_audit()),
    ):
        expected = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        if not snapshot_path(name).exists():  # first run writes the proposed snapshot
            snapshot_path(name).write_text(expected, encoding="utf-8")
        snapshot = load_snapshot(name)
        parsed = AuditReport.model_validate(snapshot)
        assert parsed.model_dump(mode="json") == snapshot
        assert snapshot_path(name).read_text(encoding="utf-8") == expected


def test_json_schema_exposes_the_versioned_report_contract() -> None:
    schema = AuditReport.model_json_schema()
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION == "0.4"
    assert set(schema["required"]) >= {"pack", "kind", "cases", "totals", "elapsed_seconds"}
    case = schema["$defs"]["CaseReport"]
    assert set(case["required"]) >= {
        "divergence_status",
        "validity",
        "execution_fidelity",
        "oracles",
        "search",
        "headline",
    }
    for separate in (
        "validity",
        "execution_fidelity",
        "oracles",
        "stability",
        "attribution_status",
    ):
        assert separate in case["properties"]


def test_checked_in_schema_validates_report_snapshots() -> None:
    schema = json.loads(Path("schemas/report-0.4.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(load_snapshot("case_report.json"))
    Draft202012Validator(schema).validate(load_snapshot("suite_report.json"))
