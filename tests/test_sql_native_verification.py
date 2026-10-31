"""Native verification of emulated (DuckDB) findings, and integer division in the translation."""

from __future__ import annotations

import importlib.util

import pytest

from isitright import CheckConfig, check
from isitright.core.evidence import DivergenceStatus, FailOn, policy_triggered
from isitright.packs.sql.dialect_fidelity import catalog_of, translate_for_duckdb
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.postgres_ddl import parse_postgres_database_schema

HAS_BOTH = all(
    importlib.util.find_spec(name) is not None
    for name in ("duckdb", "embedded_postgres", "psycopg")
)
needs_both = pytest.mark.skipif(not HAS_BOTH, reason="DuckDB and PostgreSQL extras not installed")

DDL = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected DOUBLE PRECISION)"
BOUNDARY = ("SELECT id FROM item WHERE amount > 100", "SELECT id FROM item WHERE amount >= 100")
# The known 0.2 artifact: DuckDB's / is floating point (2.5), PostgreSQL's is integer division (2).
# The translation now fixes it, so the tests switch the translation off to reproduce the artifact.
INTEGER_DIVISION = ("SELECT 5 / 2 FROM item", "SELECT 2 FROM item")


@pytest.fixture
def untranslated(monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlglot
    from sqlglot.errors import ErrorLevel

    from isitright.packs.sql import duckdb_exec
    from isitright.packs.sql.dialect_fidelity import Translation

    def plain(sql: str, catalog: object) -> Translation:
        text = sqlglot.transpile(
            sql, read="postgres", write="duckdb", unsupported_level=ErrorLevel.RAISE
        )[0]
        return Translation(text)

    monkeypatch.setattr(duckdb_exec, "translate_for_duckdb", plain)


def duck(pair: tuple[str, str], **kwargs: object):  # type: ignore[no-untyped-def]
    return check(
        engine="duckdb",
        ddl=DDL,
        reference_sql=pair[0],
        candidate_sql=pair[1],
        config=CheckConfig(max_attempts=60),
        **kwargs,  # type: ignore[arg-type]
    )


@needs_both
def test_a_true_divergence_is_re_executed_natively_and_may_fail_ci() -> None:
    report = duck(BOUNDARY)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    fidelity = report.findings[0].fidelity
    assert fidelity.found_on == "EMULATED" and fidelity.verified_on == "NATIVE_ISOLATED"
    assert fidelity.verification is not None and fidelity.verification.status == "VERIFIED"
    assert fidelity.verification.engine and fidelity.verification.engine.startswith("postgres")
    assert report.execution_fidelity.verified_on == "NATIVE_ISOLATED"
    assert report.extensions["sql"]["native_verification"] == "NATIVE_VERIFIED"
    assert policy_triggered(report, FailOn.ANY_COUNTEREXAMPLE)  # a verified finding may fail CI
    assert report.extensions["sql"]["emulation_artifact_count"] == 0


@needs_both
def test_a_known_emulation_artifact_is_excluded_when_it_fails_native_verification(
    untranslated: None,
) -> None:
    report = duck(INTEGER_DIVISION)
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert not report.findings
    sql = report.extensions["sql"]
    assert (
        sql["emulation_artifact_count"] >= 1 and sql["native_verification"] == "ARTIFACTS_EXCLUDED"
    )
    assert "emulation artifact" in sql["emulation_artifacts"][0]["note"]
    assert report.execution_fidelity.verification is not None
    assert report.execution_fidelity.verification.status == "EMULATION_ARTIFACT"
    assert "excluded as emulation artifacts" in report.headline
    assert report.search.rejected["emulation_artifact"] >= 1
    assert "not evidence of equivalence" in report.headline


@needs_both
def test_without_native_verification_the_same_artifact_is_an_unverified_emulated_finding(
    untranslated: None,
) -> None:
    report = duck(INTEGER_DIVISION, verify_native=False)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    fidelity = report.findings[0].fidelity
    assert fidelity.found_on == "EMULATED" and fidelity.verified_on is None
    assert fidelity.verification is not None and fidelity.verification.status == "NOT_VERIFIED"
    assert "turned off" in fidelity.verification.note
    assert report.extensions["sql"]["native_verification"] == "NATIVE_UNVERIFIED"
    assert not policy_triggered(report, FailOn.ANY_COUNTEREXAMPLE)  # unverified never fails CI


@needs_both
def test_an_unavailable_verifier_leaves_the_finding_unverified_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from isitright.packs.sql import hosts

    def refuse(self: object) -> object:
        raise RuntimeError("no server")

    monkeypatch.setattr(hosts.PostgresHost, "__enter__", refuse)
    report = duck(BOUNDARY)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "NOT_VERIFIED"
    assert "not available" in verification.note
    assert not policy_triggered(report, FailOn.ANY_COUNTEREXAMPLE)
    with pytest.raises(SqlInputError, match="not available"):
        duck(BOUNDARY, verify_native=True)


def test_asking_for_native_verification_without_the_extra_is_an_input_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if importlib.util.find_spec("duckdb") is None:
        pytest.skip("DuckDB not installed")
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "embedded_postgres" else real(name, *a),
    )
    with pytest.raises(SqlInputError, match="isitright\\[postgres\\]"):
        duck(BOUNDARY, verify_native=True)


@needs_both
def test_integer_division_now_agrees_on_both_engines_and_is_counted() -> None:
    """PostgreSQL: 5 / 2 is 2. DuckDB's / gives 2.5; the translation makes it truncate."""
    report = duck(("SELECT 5 / 2 FROM item", "SELECT 2 FROM item"))
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert report.extensions["sql"]["integer_division"] == {"translated": 1, "uncertain": 0}
    real = duck(("SELECT 5 / 2 FROM item", "SELECT 2.5 FROM item"))
    assert real.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert real.findings[0].fidelity.verified_on == "NATIVE_ISOLATED"  # 2 against 2.5 natively too


def test_the_translation_truncates_integer_division_and_leaves_the_rest() -> None:
    db = parse_postgres_database_schema(DDL.replace("collected", "collected"))
    catalog = catalog_of(db)

    def sql(text: str) -> str:
        return translate_for_duckdb(text, catalog).sql

    assert sql("SELECT 5 / 2") == "SELECT 5 // 2"
    assert sql("SELECT amount / 2 FROM item") == "SELECT amount // 2 FROM item"
    assert sql("SELECT id FROM item WHERE amount / 3 > 1") == (
        "SELECT id FROM item WHERE amount // 3 > 1"
    )
    # a divisor that may be zero is guarded: PostgreSQL raises, DuckDB's // gives NULL
    assert sql("SELECT SUM(amount) / COUNT(*) FROM item") == (
        "SELECT CASE WHEN COUNT(*) = 0 THEN ERROR('division by zero') "
        "ELSE SUM(amount) // COUNT(*) END FROM item"
    )
    # a double operand keeps floating-point division, as in PostgreSQL
    assert sql("SELECT amount / collected FROM item") == "SELECT amount / collected FROM item"
    assert sql("SELECT CAST(amount AS DOUBLE PRECISION) / 2 FROM item") == (
        "SELECT CAST(amount AS DOUBLE) / 2 FROM item"
    )
    assert (
        translate_for_duckdb("SELECT amount / 2 FROM item", catalog).integer_divisions_translated
        == 1
    )


def test_a_division_whose_types_cannot_be_read_is_counted_as_uncertain() -> None:
    db = parse_postgres_database_schema(DDL)
    result = translate_for_duckdb("SELECT mystery(amount) / 2 FROM item", catalog_of(db))
    assert result.integer_divisions_translated == 0 and result.divisions_uncertain == 1
    assert result.sql == "SELECT MYSTERY(amount) / 2 FROM item"


CHECK_DDL = (
    "CREATE TABLE item (id INTEGER PRIMARY KEY, v INTEGER CHECK (v >= 0), a INTEGER, "
    "b INTEGER, CONSTRAINT a_le_b CHECK (a <= b))"
)


@pytest.mark.parametrize("engine", ["postgres", "duckdb"])
def test_check_constraints_are_accepted_and_the_engine_enforces_them(engine: str) -> None:
    """Measured first: the existing PostgreSQL tests and examples reject CHECK only in a test of
    the minimal single-table parser; none needs it. It is accepted anyway (the SQLite path already
    does): the engine enforces it, simple forms guide generation."""
    if not HAS_BOTH:
        pytest.skip("DuckDB and PostgreSQL extras not installed")
    report = check(
        engine=engine,  # type: ignore[arg-type]
        ddl=CHECK_DDL,
        reference_sql="SELECT id FROM item WHERE v > 0",
        candidate_sql="SELECT id FROM item WHERE v >= 0",
        config=CheckConfig(max_attempts=80),
    )
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    rows = report.findings[0].divergence["candidate_state"]["item"]
    assert all(row["v"] is None or row["v"] >= 0 for row in rows)  # a valid state only
    assert any(row["v"] == 0 for row in rows)  # the boundary the CHECK allows
    both = check(
        engine=engine,  # type: ignore[arg-type]
        ddl=CHECK_DDL,
        reference_sql="SELECT id FROM item WHERE a < b",
        candidate_sql="SELECT id FROM item WHERE a <= b",
        config=CheckConfig(max_attempts=80),
    )
    state = both.findings[0].divergence["candidate_state"]["item"]
    assert all(r["a"] is None or r["b"] is None or r["a"] <= r["b"] for r in state)
