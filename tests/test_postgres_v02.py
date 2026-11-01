import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from isitright import CheckConfig, SuiteCase, check, check_suite
from isitright.cli import app
from isitright.core.evidence import AuditReport, CaseReport, DivergenceStatus
from isitright.packs.sql import SqlInputError, replay_report
from isitright.packs.sql.models import OrderingPolicy

HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
HAS_POSTGRES = all(
    importlib.util.find_spec(name) is not None for name in ("embedded_postgres", "psycopg")
)
DDL = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected INTEGER)"
BOUNDARY = ("SELECT id FROM item WHERE amount > 100", "SELECT id FROM item WHERE amount >= 100")
AGGREGATE = (
    "SELECT SUM(amount - collected) FROM item",
    "SELECT SUM(amount) - SUM(collected) FROM item",
)


def run(reference: str, candidate: str, **kwargs: object) -> CaseReport:
    return check(
        engine="duckdb", ddl=DDL, reference_sql=reference, candidate_sql=candidate, **kwargs
    )  # type: ignore[arg-type]


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_minimizes_and_replays_with_domain_rules() -> None:
    constraints = {"properties": {"item": {"type": "array", "minItems": 2}}}
    result = run(*AGGREGATE, constraints=constraints)
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert "DOMAIN_VALIDATED" in result.validity.tiers
    assert sum(result.search.rejected.values()) >= 1
    (finding,) = result.findings
    assert finding.minimization["complete"] is True
    assert finding.minimization["attempts"] <= 6
    assert len(finding.divergence["candidate_state"]["item"]) == 2
    replayed = replay_report(result)
    assert replayed["reproduced"] is True
    assert replayed["version_matches"] is True
    AuditReport.model_validate({**_audit(result)})


def _audit(case: CaseReport) -> dict[str, object]:
    from isitright.packs.sql.reports import case_audit

    return case_audit(case).model_dump(mode="json")


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_domain_rejections_are_not_counterexamples() -> None:
    constraints = {
        "properties": {
            "item": {"items": {"properties": {"amount": {"type": "integer", "maximum": 99}}}}
        }
    }
    result = run(*BOUNDARY, constraints=constraints)
    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert sum(result.search.rejected.values()) > 0
    assert result.findings == []
    no_valid = run(*BOUNDARY, constraints={"not": {}})
    assert no_valid.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert no_valid.search.executed == 0


def test_remote_constraints_are_rejected_without_network() -> None:
    with pytest.raises(SqlInputError, match="remote"):
        run(*BOUNDARY, constraints={"$ref": "https://example.org/schema"})


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_replay_never_executes_state_values_as_sql() -> None:
    report = run(*BOUNDARY)
    rows = report.findings[0].divergence["candidate_state"]["item"]
    rows[0]["amount"] = "100); DROP TABLE item; --"
    with pytest.raises(ValueError):
        replay_report(report)


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_replay_rechecks_domain_constraints() -> None:
    report = run(*BOUNDARY, constraints={})
    report.inputs["constraints"] = {"not": {}}
    with pytest.raises(SqlInputError, match="violates"):
        replay_report(report)


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_order_policy_and_duplicate_multiplicity() -> None:
    ordered = run("SELECT id FROM item ORDER BY id ASC", "SELECT id FROM item ORDER BY id DESC")
    assert ordered.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert ordered.comparison_policy["effective_ordering"] == "ordered"
    assert replay_report(ordered)["reproduced"]
    unordered = run(
        "SELECT id FROM item ORDER BY id ASC",
        "SELECT id FROM item ORDER BY id DESC",
        config=CheckConfig(ordering_policy=OrderingPolicy.UNORDERED),
    )
    assert unordered.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    duplicate = run("SELECT amount FROM item", "SELECT DISTINCT amount FROM item")
    assert duplicate.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert duplicate.findings[0].mutation_path[-1].family in {"duplicate", "boundary", "missing"}


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_suite_ranks_findings_and_keeps_unsupported_cases() -> None:
    cases = [
        SuiteCase(
            case_id="same",
            reference_sql="SELECT COUNT(*) FROM item",
            candidate_sql="SELECT COUNT(*) FROM item",
        ),
        SuiteCase(
            case_id="unsupported", reference_sql="SELECT pg_sleep(1)", candidate_sql="SELECT 1"
        ),
        SuiteCase(case_id="boundary", reference_sql=BOUNDARY[0], candidate_sql=BOUNDARY[1]),
    ]
    suite = check_suite(engine="duckdb", ddl=DDL, cases=cases, verify_native=False)
    assert [case.case_id for case in suite.cases] == ["boundary", "unsupported", "same"]
    assert suite.totals.by_divergence_status == {
        "COUNTEREXAMPLE_FOUND": 1,
        "UNSUPPORTED": 1,
        "NOT_FOUND_WITHIN_BUDGET": 1,
    }
    assert suite.cases[0].execution_fidelity.found_on == "EMULATED"
    assert suite.cases[0].execution_fidelity.verified_on is None
    verified = check_suite(engine="duckdb", ddl=DDL, cases=cases[2:])
    assert verified.cases[0].execution_fidelity.verified_on == "NATIVE_ISOLATED"


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_suite_cli_and_replay(tmp_path: Path) -> None:
    schema = tmp_path / "schema.sql"
    cases = tmp_path / "cases.jsonl"
    schema.write_text(DDL, encoding="utf-8")
    cases.write_text(
        json.dumps(
            {"case_id": "boundary", "reference_sql": BOUNDARY[0], "candidate_sql": BOUNDARY[1]}
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--engine",
            "duckdb",
            "--schema",
            str(schema),
            "--cases",
            str(cases),
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "C [1/1]" in result.output
    assert "not been checked on PostgreSQL" in result.output
    report = output / "cases" / "0001-boundary" / "case_report.json"
    assert report.is_file()
    assert (output / "suite_report.md").is_file()
    replay = runner.invoke(app, ["sql", "replay", str(report)])
    assert replay.exit_code == 0, replay.output
    assert "Reproduced both query outputs" in replay.output


@pytest.mark.skipif(not HAS_POSTGRES, reason="optional PostgreSQL dependencies not installed")
def test_native_suite_and_native_replay() -> None:
    suite = check_suite(
        engine="postgres",
        ddl=DDL,
        cases=[
            SuiteCase(case_id="boundary", reference_sql=BOUNDARY[0], candidate_sql=BOUNDARY[1]),
            SuiteCase(case_id="same", reference_sql="SELECT 2", candidate_sql="SELECT 5 / 2"),
        ],
    )
    assert [case.divergence_status.value for case in suite.cases] == [
        "COUNTEREXAMPLE_FOUND",
        "NOT_FOUND_WITHIN_BUDGET",
    ]
    assert {case.execution_fidelity.found_on for case in suite.cases} == {"NATIVE_ISOLATED"}
    result = replay_report(suite.cases[0])
    assert result["reproduced"] is True
    assert result["execution_engine"] == "postgres"


@pytest.mark.parametrize(
    "options, message",
    [
        ({"engine": "other"}, "engine"),
    ],
)
def test_suite_rejects_invalid_configuration(options: dict, message: str) -> None:
    with pytest.raises(SqlInputError, match=message):
        check_suite(ddl=DDL, cases=[], **options)


@pytest.mark.parametrize(
    "options",
    [{"max_attempts": 0}, {"timeout_seconds": 0}, {"max_result_rows": 0}],
)
def test_budgets_must_be_positive(options: dict) -> None:
    with pytest.raises(ValidationError):
        CheckConfig(**options)
    assert CheckConfig(minimization_max_attempts=0).minimization_max_attempts == 0
    with pytest.raises(ValidationError):
        CheckConfig(minimization_max_attempts=-1)


def test_suite_rejects_duplicate_ids_and_empty_native_does_not_claim_execution() -> None:
    case = SuiteCase(case_id="same", reference_sql="SELECT 1", candidate_sql="SELECT 1")
    with pytest.raises(Exception, match="unique"):
        check_suite(engine="postgres", ddl=DDL, cases=[case, case])
    result = check_suite(engine="postgres", ddl=DDL, cases=[])
    assert result.totals.cases == 0 and result.cases == []


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_suite_preserves_unexpected_case_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from isitright.packs.sql import audit

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("engine failed")

    monkeypatch.setattr(audit.SqlAudit, "check", fail)
    case = SuiteCase(case_id="bad", reference_sql="SELECT 1", candidate_sql="SELECT 1")
    suite = check_suite(engine="duckdb", ddl=DDL, cases=[case])
    assert suite.cases[0].divergence_status is DivergenceStatus.INCONCLUSIVE
    assert "engine failed" in suite.cases[0].errors[0]["message"]


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_report_invariants_and_replay_validation() -> None:
    report = run(*BOUNDARY)
    data = report.model_dump(mode="json")
    for changes in (
        {"divergence_status": "NOT_FOUND_WITHIN_BUDGET"},
        {"execution_fidelity": {"found_on": "NATIVE_ISOLATED", "engine": "duckdb 1"}},
        {"execution_fidelity": {"found_on": "EMULATED", "engine": "postgres 18"}},
    ):
        with pytest.raises(ValidationError):
            CaseReport.model_validate({**data, **changes})
    for options in ({"timeout_seconds": 0}, {"max_result_rows": 0}):
        with pytest.raises(SqlInputError, match="budgets"):
            replay_report(report, **options)
    no_evidence = run("SELECT 1", "SELECT 1")
    with pytest.raises(SqlInputError, match="counterexample"):
        replay_report(no_evidence)
    tiers = ["STRUCTURAL", "DOMAIN_VALIDATED"]
    lacking = report.model_copy(
        update={
            "findings": [
                report.findings[0].model_copy(
                    update={
                        "validity": report.findings[0].validity.model_copy(update={"tiers": tiers})
                    }
                )
            ]
        }
    )
    with pytest.raises(SqlInputError, match="lacks"):
        replay_report(lacking)
    with pytest.raises(SqlInputError, match="invalid domain constraints"):
        replay_report(report.model_copy(update={"inputs": {**report.inputs, "constraints": "bad"}}))
    with pytest.raises(SqlInputError, match="ordering"):
        replay_report(
            report.model_copy(
                update={"comparison_policy": {**report.comparison_policy, "ordering": "invalid"}}
            )
        )


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_check_cli_findings_and_fail_policy(tmp_path: Path) -> None:
    schema = tmp_path / "schema.sql"
    ref = tmp_path / "ref.sql"
    candidate = tmp_path / "candidate.sql"
    schema.write_text(DDL, encoding="utf-8")
    ref.write_text(BOUNDARY[0], encoding="utf-8")
    candidate.write_text(BOUNDARY[1], encoding="utf-8")
    args = [
        "sql",
        "check",
        "--engine",
        "duckdb",
        "--schema",
        str(schema),
        "--reference",
        str(ref),
        "--candidate",
        str(candidate),
        "--output-dir",
        str(tmp_path / "out"),
        "--fail-on",
        "any-counterexample",
        "--no-verify-native",
    ]
    runner = CliRunner()
    result = runner.invoke(app, args)
    # An emulated, natively unverified finding does not fail CI by default.
    assert result.exit_code == 0, result.output
    assert "Generated counterexample" in result.output
    assert (tmp_path / "out" / "counterexample.sql").exists()
    assert runner.invoke(app, args).exit_code == 2
    # The same finding, re-executed natively, is verified and may fail CI (exit code 3).
    native = [a for a in args if a != "--no-verify-native"]
    native[native.index(str(tmp_path / "out"))] = str(tmp_path / "out-native")
    if HAS_POSTGRES:
        assert runner.invoke(app, native).exit_code == 3


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_suite_cli_replay_failure(tmp_path: Path) -> None:
    schema = tmp_path / "schema.sql"
    cases = tmp_path / "cases.jsonl"
    schema.write_text(DDL, encoding="utf-8")
    cases.write_text(
        json.dumps(
            {"case_id": "boundary", "reference_sql": BOUNDARY[0], "candidate_sql": BOUNDARY[1]}
        )
        + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    output = tmp_path / "suite"
    args = [
        "sql",
        "suite",
        "--engine",
        "duckdb",
        "--schema",
        str(schema),
        "--cases",
        str(cases),
        "--output-dir",
        str(output),
    ]
    assert runner.invoke(app, args).exit_code == 0
    assert runner.invoke(app, args).exit_code == 2
    report_path = output / "cases" / "0001-boundary" / "case_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    case = report["cases"][0]
    case["execution_fidelity"]["engine"] = "duckdb different-version"
    divergence = case["findings"][0]["divergence"]
    divergence["reference_result"] = divergence["candidate_result"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    replay = runner.invoke(app, ["sql", "replay", str(report_path)])
    assert replay.exit_code == 1
    assert "did not reproduce" in replay.output
    assert "version differs" in replay.output
    report_path.write_text("not JSON", encoding="utf-8")
    assert runner.invoke(app, ["sql", "replay", str(report_path)]).exit_code == 1
