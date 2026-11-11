"""A candidate that errors on a valid world where the reference returns a result is a finding of
its own kind ("candidate errors") for the warehouse dialects, confirmed natively when a host runs.

Proposed fixture: pending owner review (constructed schema and queries, written by Claude)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import BigQueryHost, check
from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    ComparisonPolicy,
    QueryResult,
    ResultColumn,
)
from isitright.packs.sql.replaying import export_eval_cases, replay_report
from isitright.packs.sql.results import error_result, is_error_result

DDL = "CREATE TABLE t (id INT64, s STRING)"
SAFE = "SELECT id, SAFE_CAST(s AS INT64) AS n FROM t"
PLAIN = "SELECT id, CAST(s AS INT64) AS n FROM t"


def test_an_error_result_is_a_one_row_text_result_and_is_recognized() -> None:
    result = error_result("ConversionException: could not convert 'x'\n\nLINE 1: SELECT")
    assert is_error_result(result)
    assert result.rows[0][0].value == "ConversionException: could not convert 'x'"  # first line
    ordinary = QueryResult(
        columns=[ResultColumn(name="query_error")],
        rows=[[CanonicalValue(kind=CanonicalValueKind.TEXT, value="a text")]],
    )
    assert not is_error_result(ordinary)


def test_comparing_an_error_result_with_a_result_names_the_candidate() -> None:
    reference = QueryResult(
        columns=[ResultColumn(name="n")],
        rows=[[CanonicalValue(kind=CanonicalValueKind.INTEGER, value=1)]],
    )
    outcome = compare_results(reference, error_result("boom"), policy=ComparisonPolicy())
    assert not outcome.matches and outcome.difference == "candidate errors: boom"


def test_a_candidate_that_errors_where_the_reference_does_not_is_a_finding() -> None:
    report = check(reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert "candidate errors" in report.headline
    finding = report.findings[0]
    assert finding.divergence["kind"] == "candidate_errors"
    assert finding.divergence["difference"].startswith("candidate errors: ")
    assert is_error_result(QueryResult.model_validate(finding.divergence["candidate_result"]))
    assert finding.fidelity.found_on == "EMULATED"
    assert finding.divergence["reproduces"] is True
    # the replay and the exported eval case reproduce it
    assert replay_report(report)["reproduced"] is True
    assert export_eval_cases(report)[0].expectation["outputs_differ"] is True


def test_the_reference_erroring_or_both_erroring_is_still_not_a_finding() -> None:
    reversed_pair = check(reference_sql=PLAIN, candidate_sql=SAFE, dialect="bigquery", ddl=DDL)
    assert reversed_pair.findings == []
    both = check(reference_sql=PLAIN, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL)
    assert both.findings == []


def test_ordinary_divergences_do_not_carry_the_kind() -> None:
    report = check(
        reference_sql="SELECT id FROM t WHERE id > 1",
        candidate_sql="SELECT id FROM t WHERE id >= 1",
        dialect="bigquery",
        ddl=DDL,
    )
    assert report.findings and "kind" not in report.findings[0].divergence


class _Job:
    def __init__(self, names: Any = (), rows: Any = (), error: bool = False) -> None:
        self.error = error
        self.total_bytes_processed = 0
        self.total_bytes_billed = 0
        self.job_id = "job"
        self.schema = [
            type("F", (), {"name": n, "field_type": "INTEGER", "mode": "NULLABLE"})() for n in names
        ]
        self._rows = list(rows)

    def result(self, timeout: Any = None, max_results: Any = None) -> list[Any]:
        if self.error:  # BigQuery raises a data-dependent error when the job's result is read
            raise RuntimeError("Bad int64 value")
        return self._rows


class _Client:
    def __init__(self, candidate_errors: bool) -> None:
        self.candidate_errors = candidate_errors

    def query(self, sql: str, job_config: dict[str, Any], location: Any = None) -> _Job:
        if job_config.get("dry_run"):
            return _Job()
        return _Job(
            ["id", "n"], [(10, None)], error=self.candidate_errors and "SAFE_CAST" not in sql
        )


def _confirmed(candidate_errors: bool) -> Any:
    host = BigQueryHost(
        client_factory=lambda: _Client(candidate_errors), config_factory=lambda **kw: kw
    )
    return check(reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, confirm=host)


def test_the_error_is_confirmed_when_the_candidate_errors_natively_too() -> None:
    finding = _confirmed(True).findings[0]
    assert finding.fidelity.verified_on == "NATIVE_INLINE"
    assert finding.fidelity.verification.status == "VERIFIED"
    assert finding.divergence["kind"] == "candidate_errors"
    native = finding.divergence["native_results"]
    assert native["candidate_result"]["rows"][0][0]["engine_type"] == "query_error"


def test_an_error_that_does_not_happen_natively_is_an_emulation_artifact() -> None:
    report = _confirmed(False)
    assert report.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert report.findings == []
    assert report.extensions["sql"]["emulation_artifact_count"] == 1


def test_an_error_at_the_dry_run_is_not_a_confirmation() -> None:
    """BigQuery refuses a bad query at the dry run, whatever the data: that is a static error, so
    the finding stays unverified instead of being called a data-dependent error."""

    class Static(_Client):
        def query(self, sql: str, job_config: dict[str, Any], location: Any = None) -> _Job:
            if job_config.get("dry_run") and "SAFE_CAST" not in sql:
                raise RuntimeError("No matching signature")
            return super().query(sql, job_config, location)

    host = BigQueryHost(client_factory=lambda: Static(True), config_factory=lambda **kw: kw)
    report = check(
        reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, confirm=host
    )
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "NOT_VERIFIED"
    assert "native run failed" in verification.note


# --- gold trusted ---------------------------------------------------------------------------------


def test_gold_trusted_is_recorded_and_an_untrusted_reference_is_said_beside_a_finding() -> None:
    plain = check(reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL)
    assert "gold_trusted" not in plain.inputs  # unknown: nothing is recorded
    untrusted = check(
        reference_sql=SAFE,
        candidate_sql=PLAIN,
        dialect="bigquery",
        ddl=DDL,
        gold_trusted=False,
        gold_trust_basis="does not reproduce the published result on the real data",
    )
    assert untrusted.inputs["gold_trusted"] == {
        "value": False,
        "basis": "does not reproduce the published result on the real data",
    }
    assert "marked untrusted" in untrusted.headline
    assert any("marked untrusted" in a for a in untrusted.assumptions)
    trusted = check(
        reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, gold_trusted=True
    )
    assert trusted.inputs["gold_trusted"]["value"] is True
    assert "untrusted" not in trusted.headline


def test_a_suite_case_carries_gold_trusted() -> None:
    from isitright.packs.sql import SuiteCase, check_suite

    report = check_suite(
        cases=[
            SuiteCase(
                case_id="a",
                reference_sql=SAFE,
                candidate_sql=PLAIN,
                gold_trusted=False,
                gold_trust_basis="stated in the suite",
            )
        ],
        dialect="bigquery",
        ddl=DDL,
    )
    assert report.cases[0].inputs["gold_trusted"]["value"] is False
    assert "gold_trusted" not in report.cases[0].extensions.get("metadata", {})


def test_a_finding_verified_only_on_the_unminimized_world_says_so() -> None:
    """Native confirmation runs on the minimized world first; when only the larger world found
    before minimizing differs natively, the verification note says the minimal example is not
    itself confirmed (found in review of the Spider case bq284, where the emulation's
    ``count_if`` gave NULL on the minimized state)."""

    class OnlyTheSecondWorld(_Client):
        candidate_calls = 0

        def query(self, sql: str, job_config: dict[str, Any], location: Any = None) -> _Job:
            if job_config.get("dry_run"):
                return _Job()
            if "SAFE_CAST" in sql:
                return _Job(["id", "n"], [(10, None)])
            self.candidate_calls += 1
            return _Job(["id", "n"], [(10, None)], error=self.candidate_calls > 1)

    client = OnlyTheSecondWorld(True)
    host = BigQueryHost(client_factory=lambda: client, config_factory=lambda **kw: kw)
    report = check(
        reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, confirm=host
    )
    finding = report.findings[0]
    worlds = [c["world"] for c in finding.divergence["native_confirmation"]]
    assert worlds == ["minimized", "unminimized divergent"]
    assert finding.fidelity.verification.status == "VERIFIED"
    assert "not itself confirmed" in finding.fidelity.verification.note
