import importlib.util
import json
from pathlib import Path

import pytest

from isitright import CheckConfig, SuiteCase, check, check_suite

EXAMPLES = Path(__file__).parents[1] / "examples" / "sqlite"


def _create_database(path: Path, *, schema_only: bool = False) -> Path:
    spec = importlib.util.spec_from_file_location(
        "create_database", EXAMPLES / "create_database.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import sys

    argv = ["create_database.py", str(path), *(["--schema-only"] if schema_only else [])]
    original, sys.argv = sys.argv, argv
    try:
        module.main()
    finally:
        sys.argv = original
    return path


@pytest.mark.parametrize("schema_only", [False, True])
def test_sqlite_quick_start_finds_the_null_counterexample(
    tmp_path: Path, schema_only: bool
) -> None:
    database = _create_database(tmp_path / "example.sqlite", schema_only=schema_only)
    result = check(
        database=database,
        reference_sql=(EXAMPLES / "reference.sql").read_text(encoding="utf-8"),
        candidate_sql=(EXAMPLES / "candidate.sql").read_text(encoding="utf-8"),
        constraints_file=EXAMPLES / "constraints.yaml",
        config=CheckConfig(),
    )
    assert result.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert "DOMAIN_VALIDATED" in result.validity.tiers
    assert result.original_state["outputs_match"] is True


def test_sqlite_example_suite_has_two_counterexamples_and_one_agreement(tmp_path: Path) -> None:
    database = _create_database(tmp_path / "example.sqlite")
    suite = check_suite(
        database=database,
        cases=EXAMPLES / "cases.jsonl",
        constraints_file=EXAMPLES / "constraints.yaml",
        config=CheckConfig(),
    )
    assert {case.case_id: case.divergence_status.value for case in suite.cases} == {
        "null-shortfall": "COUNTEREXAMPLE_FOUND",
        "province-count": "COUNTEREXAMPLE_FOUND",
        "equivalent": "NOT_FOUND_WITHIN_BUDGET",
    }


def test_example_case_files_are_valid_suite_input() -> None:
    for path in (
        EXAMPLES / "cases.jsonl",
        EXAMPLES.parent / "postgres" / "cases.jsonl",
    ):
        cases = [
            SuiteCase.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert cases


POSTGRES = EXAMPLES.parent / "postgres"
HAS_NATIVE = all(importlib.util.find_spec(name) for name in ("embedded_postgres", "psycopg"))


def _read(name: str) -> str:
    return (POSTGRES / name).read_text(encoding="utf-8")


@pytest.mark.skipif(not HAS_NATIVE, reason="optional PostgreSQL dependencies not installed")
def test_postgres_quick_start_examples_find_the_documented_differences() -> None:
    from tests.pgcompat import check_postgres, check_postgres_suite

    single = check_postgres(
        ddl=_read("schema.sql"),
        reference_sql=_read("reference.sql"),
        candidate_sql=_read("candidate.sql"),
    )
    assert single.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert single.execution_fidelity.found_on == "NATIVE_ISOLATED"

    related = check_postgres(
        ddl=_read("multitable-schema.sql"),
        reference_sql=_read("multitable-reference.sql"),
        candidate_sql=_read("multitable-candidate.sql"),
    )
    assert related.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    # The 0.2 "join" family is now the generic families (a parent without a child).
    assert related.findings[0].mutation_path[-1].family in {"duplicate", "missing", "empty"}

    cases = [
        SuiteCase.model_validate(json.loads(line))
        for line in _read("cases.jsonl").splitlines()
        if line.strip()
    ]
    suite = check_postgres_suite(ddl=_read("schema.sql"), cases=cases)
    assert {case.case_id: case.divergence_status.value for case in suite.cases} == {
        "boundary": "COUNTEREXAMPLE_FOUND",
        "null-count": "COUNTEREXAMPLE_FOUND",
        "same-count": "NOT_FOUND_WITHIN_BUDGET",
    }
