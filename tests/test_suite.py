from io import StringIO
from pathlib import Path

import pytest

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql.suite import SuiteInputError, load_suite_cases, parse_suite_lines
from tests.factories import make_audit, make_case


def test_unknown_jsonl_fields_are_preserved_as_metadata() -> None:
    cases = parse_suite_lines(
        StringIO(
            '{"case_id":"q1","reference_sql":"SELECT 1",'
            '"candidate_sql":"SELECT 1","difficulty":"easy"}\n'
        )
    )
    assert cases[0].metadata == {"difficulty": "easy"}


def test_duplicate_case_ids_report_line_number() -> None:
    lines = [
        '{"case_id":"q1","reference_sql":"SELECT 1","candidate_sql":"SELECT 1"}',
        '{"case_id":"q1","reference_sql":"SELECT 2","candidate_sql":"SELECT 2"}',
    ]
    with pytest.raises(SuiteInputError, match="line 2"):
        parse_suite_lines(lines)


def test_synthetic_suite_is_independent_and_has_designed_divergences() -> None:
    path = Path("tests/fixtures/proposals/synthetic_acceptance_cases.jsonl")
    cases = load_suite_cases(path)
    assert len(cases) == 17
    designed = [case for case in cases if case.metadata["deliberate_latent_divergence"]]
    assert [case.case_id for case in designed] == [
        "log-001",
        "log-002",
        "log-003",
        "log-004",
        "log-005",
    ]
    assert {case.metadata["mutation_family"] for case in cases} == {
        "boundary",
        "null",
        "duplicate",
        "join",
        "filtering",
        "aggregation",
    }
    assert all(case.metadata["attribution"] == "UNDETERMINED" for case in cases)
    window_case = next(case for case in cases if case.case_id == "log-014")
    assert window_case.metadata["expected_future_status"] == "AGREEMENT_ON_TESTED_STATES"


def test_suite_ranking_is_evidence_first_and_stable() -> None:
    agreement = make_case("agreement", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ())
    unsupported = make_case("unsupported", DivergenceStatus.UNSUPPORTED, ())
    schema = make_case("schema", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL",))
    tiers = ("STRUCTURAL", "DOMAIN_VALIDATED")
    domain_a = make_case("domain-a", DivergenceStatus.COUNTEREXAMPLE_FOUND, tiers)
    domain_b = make_case("domain-b", DivergenceStatus.COUNTEREXAMPLE_FOUND, tiers)
    suite = make_audit(agreement, domain_a, unsupported, schema, domain_b)
    assert [case.case_id for case in suite.ranked()] == [
        "domain-a",
        "domain-b",
        "schema",
        "unsupported",
        "agreement",
    ]
