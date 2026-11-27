import json
import os
from pathlib import Path

from pytest import MonkeyPatch

from isitright.core.evidence import (
    CaseReport,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    MutationRecord,
    OracleRecord,
    ValidityRecord,
)
from isitright.core.shown import built_from
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    QueryResult,
    ResultColumn,
)
from isitright.packs.sql.reports import ReportFormat, write_case_report, write_suite_report
from tests.factories import make_audit, make_case


def test_writes_deterministic_json_and_markdown(tmp_path: Path) -> None:
    result = make_case("q1", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET)
    paths = write_case_report(result, tmp_path, ReportFormat.BOTH)

    assert paths == [tmp_path / "case_report.json", tmp_path / "case_report.md"]
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "0.9"
    markdown = paths[1].read_text(encoding="utf-8")
    assert "No difference found within the budget" in markdown
    assert "Technical details" in markdown


def test_report_formats_and_diagnostic_sections(tmp_path: Path) -> None:
    result = make_case(
        "q1",
        DivergenceStatus.INCONCLUSIVE,
        original_state={"outputs_match": None, "note": "Timed out"},
        errors=[{"code": "QUERY_TIMEOUT", "message": "Timed out", "phase": "query"}],
    )

    json_paths = write_case_report(result, tmp_path / "json", ReportFormat.JSON)
    markdown_paths = write_case_report(result, tmp_path / "markdown", ReportFormat.MARKDOWN)

    assert [path.name for path in json_paths] == ["case_report.json"]
    assert [path.name for path in markdown_paths] == ["case_report.md"]
    markdown = markdown_paths[0].read_text(encoding="utf-8")
    assert "Original-state diagnostic" in markdown
    assert "QUERY_TIMEOUT" in markdown


def _counterexample_case(case_id: str, *, generated: bool) -> CaseReport:
    reference = QueryResult(
        columns=[ResultColumn(name="name")],
        rows=[
            [CanonicalValue(kind=CanonicalValueKind.TEXT, value="Achaea")],
            [CanonicalValue(kind=CanonicalValueKind.TEXT, value="Macedonia")],
        ],
    )
    candidate = QueryResult(
        columns=[ResultColumn(name="province_name")],
        rows=list(reversed(reference.rows)),
    )
    validity = ValidityRecord(status="VALID", tiers=["STRUCTURAL"])
    finding = Finding(
        finding_id=f"{case_id}:1",
        world_id="missing" if generated else "original_state",
        validity=validity,
        oracles=[OracleRecord(name="reference_sql", kind="REFERENCE_PROGRAM", outcome="NOT_MET")],
        mutation_path=(
            [MutationRecord(family="missing", target="state", description="provinces.region null")]
            if generated
            else []
        ),
        divergence={
            "reference_result": reference.model_dump(mode="json"),
            "candidate_result": candidate.model_dump(mode="json"),
            "difference": "ordered row 0 differs",
            "candidate_state": {"provinces": [{"name": "Achaea"}]},
            "reproducer_sql": "-- fixture\n",
            "original_injected_change": (
                "Set provinces.region to NULL" if generated else "No generated mutation"
            ),
            "generator": "missing" if generated else "original_state",
        },
        fidelity=FidelityRecord(found_on="NATIVE_ISOLATED", engine="sqlite 3"),
        minimization={"complete": True, "attempts": 3, "rows_before": 15, "rows_after": 2},
        world_fingerprint="a" * 16,
        built_from=built_from("a" * 16, "validity", "world_diff", "divergence", "replay"),
        headline="Evidence recorded for review",
    )
    return make_case(
        case_id,
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
        findings=[finding],
        headline=(
            "Generated counterexample: queries diverge after a missing mutation"
            if generated
            else "Original-data mismatch: queries return different results"
        ),
        original_state={"outputs_match": generated},
        inputs={
            "reference_sql": "SELECT name FROM provinces",
            "candidate_sql": "SELECT province_name FROM provinces",
        },
        extensions={
            "sql": {"execution_engine": "sqlite", "schema_ddl": ["CREATE TABLE provinces (name)"]}
        },
    )


def test_case_markdown_leads_with_explanation_and_copyable_replay(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    output = Path("artifacts") / "case"
    result = _counterexample_case("q-order", generated=False)

    paths = write_case_report(result, output)
    markdown = (output / "case_report.md").read_text(encoding="utf-8")
    payload = json.loads((output / "case_report.json").read_text(encoding="utf-8"))
    finding = payload["cases"][0]["findings"][0]

    assert output / "case_report.md" in paths
    assert "Original-data mismatch" in markdown
    assert "same rows, but in a different order" in markdown
    assert "## What to do next" in markdown
    assert "## Technical details" in markdown
    expected_report = str(output / "case_report.json")
    assert expected_report in finding["replay"]["command"]
    # 0.8.1: the artifact is named relative to the report file, and the command is absolute
    assert finding["replay"]["artifact"] == "replay.json"
    assert (
        payload["cases"][0]["headline"]
        == "Original-data mismatch: queries return different results"
    )
    assert (output / "replay.json").is_file() and (output / "counterexample.sql").is_file()


def test_replay_command_names_no_directory_and_the_artifact_is_relative_to_the_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """0.8.1: a report names no directory of the machine that wrote it. The command carries the
    report's location as a placeholder and the artifact is named relative to the report file; the
    old test of a fall back to absolute paths (when a relative path could not be made) no longer
    applies because no path is made."""
    output = tmp_path / "artifacts"
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    write_case_report(_counterexample_case("cross-drive", generated=False), output)
    payload = json.loads((output / "case_report.json").read_text(encoding="utf-8"))
    finding = payload["cases"][0]["findings"][0]

    assert finding["replay"]["command"] == "isitright sql replay <case_report.json>"
    assert finding["replay"]["artifact"] == "replay.json"
    assert str(tmp_path) not in json.dumps(payload)


def test_suite_markdown_separates_original_and_generated_findings(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    original = _counterexample_case("original", generated=False)
    generated = _counterexample_case("generated", generated=True)
    agreement = make_case("agreement", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET)
    suite = make_audit(original, generated, agreement)

    write_suite_report(suite, Path("artifacts") / "suite")
    markdown = (Path("artifacts") / "suite" / "suite_report.md").read_text(encoding="utf-8")
    payload = json.loads(
        (Path("artifacts") / "suite" / "suite_report.json").read_text(encoding="utf-8")
    )

    assert "1 original-data mismatches" in markdown
    assert "1 generated counterexamples" in markdown
    assert "| 1 | `original` | Original-data mismatch |" in markdown
    assert "cases/" in markdown
    replay = payload["cases"][0]["findings"][0]["replay"]["command"]
    assert f"artifacts{os.sep}suite{os.sep}cases{os.sep}0001-original" in replay
