import importlib.util
import json
from pathlib import Path

import pytest
import sqlglot
from typer.testing import CliRunner

from isitright import CheckConfig, check
from isitright.cli import _print_case_summary, app
from isitright.core.evidence import DivergenceStatus
from isitright.core.hints import Hints
from isitright.core.mutations import World
from isitright.core.spec import WorldSpec
from isitright.packs.sql.analysis import SqlStatement, harvest_query_guidance
from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from isitright.packs.sql.hints import hints_from_guidance
from isitright.packs.sql.mapping import build_model, generate_base_state, to_state
from isitright.packs.sql.postgres_ddl import parse_query, parse_schema
from isitright.packs.sql.postgres_server import _postgres_server, _temporary_postgres_directory
from tests.factories import make_case

DDL = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected INTEGER)"
DDL_FLOAT = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected DOUBLE PRECISION)"
BOUNDARY = ("SELECT id FROM item WHERE amount > 100", "SELECT id FROM item WHERE amount >= 100")
NULL_COUNT = ("SELECT COUNT(*) FROM item", "SELECT COUNT(amount) FROM item")
AGGREGATE = (
    "SELECT SUM(amount - collected) FROM item",
    "SELECT SUM(amount) - SUM(collected) FROM item",
)
HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
HAS_POSTGRES = all(
    importlib.util.find_spec(name) is not None for name in ("embedded_postgres", "psycopg")
)


def duck(reference: str, candidate: str, **kwargs: object):  # type: ignore[no-untyped-def]
    return check(
        engine="duckdb", ddl=DDL, reference_sql=reference, candidate_sql=candidate, **kwargs
    )  # type: ignore[arg-type]


def test_temporary_postgres_directory_is_created_without_mkdtemp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "isitright.packs.sql.postgres_server.tempfile.gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "isitright.packs.sql.postgres_server.tempfile.TemporaryDirectory",
        lambda *args, **kwargs: pytest.fail("TemporaryDirectory must not be used"),
    )

    with _temporary_postgres_directory() as directory:
        assert directory.parent == tmp_path
        assert directory.name.startswith("isitright-pg-")
        assert directory.is_dir()

    assert not directory.exists()


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE item (id INTEGER PRIMARY KEY, v INTEGER CHECK (v > 0))",
        "CREATE TABLE item (id INTEGER, v INTEGER)",
        "CREATE TABLE item (id INTEGER PRIMARY KEY, v TEXT NOT NULL)",
        "CREATE TABLE item (id INTEGER PRIMARY KEY, v INTEGER); DROP TABLE item",
        "CREATE TABLE item (id INTEGER PRIMARY KEY, v INTEGER REFERENCES other(id))",
        "CREATE TABLE item (id INTEGER PRIMARY KEY, v DOUBLE PRECISION)",
    ],
)
def test_schema_rejects_unsupported_constructs(ddl: str) -> None:
    with pytest.raises(PostgresInputError):
        parse_schema(ddl)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT pg_sleep(2)",
        "SELECT * FROM read_csv('/private/file')",
        "SELECT * FROM other",
        "SELECT id FROM item; DELETE FROM item",
        "WITH x AS (DELETE FROM item RETURNING id) SELECT * FROM x",
        "SELECT item.id FROM item JOIN other ON item.id = other.id",
        "SELECT nonexistent FROM item",
        "SELECT item.id FROM item",
    ],
)
def test_queries_fail_closed(query: str) -> None:
    with pytest.raises(PostgresInputError):
        parse_query(query, parse_schema(DDL))


def test_generation_uses_schema_columns_and_query_boundaries() -> None:
    schema = parse_schema("CREATE TABLE records (key INTEGER PRIMARY KEY, score INTEGER)")
    model = build_model(schema.database, "postgres")
    base = generate_base_state(model, [])
    assert base is not None
    spec = WorldSpec("t", model.schema)

    def descriptions(low: str, high: str) -> list[str]:
        statements = [
            SqlStatement(parse_query(sql, schema), top_level_ordered=False) for sql in (low, high)
        ]
        hints: Hints = hints_from_guidance(model, harvest_query_guidance(*statements))
        from isitright.core.families import default_mutators

        world = World(to_state(model, base))
        return [
            m.description
            for mutator in default_mutators(insert_variants=True)
            for m in mutator.propose(spec, world, hints)
        ]

    positive = descriptions(
        "SELECT key FROM records WHERE score > 37", "SELECT key FROM records WHERE score >= 37"
    )
    assert any(d.endswith("score = 37") for d in positive)
    assert any(d.endswith("score = None") for d in positive)
    negative = descriptions(
        "SELECT key FROM records WHERE score > -37", "SELECT key FROM records WHERE score >= -37"
    )
    assert any(d.endswith("score = -37") for d in negative)


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
@pytest.mark.parametrize("pair", [BOUNDARY, NULL_COUNT, AGGREGATE])
def test_emulated_finds_and_replays_small_counterexamples(pair: tuple[str, str]) -> None:
    import duckdb

    result = duck(
        *pair, verify_native=False
    )  # the unverified label; see test_sql_native_verification
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert result.execution_fidelity.found_on == "EMULATED"
    sql = result.extensions["sql"]
    assert sql["native_verification"] == "NATIVE_UNVERIFIED"
    assert result.validity.tiers == ["STRUCTURAL"]
    assert result.execution_fidelity.engine.startswith("duckdb")
    assert sql["translation_status"] == "APPLIED"
    assert sql["executed_reference_sql"]
    assert result.attribution_status.value == "UNDETERMINED"
    assert result.original_state["outputs_match"] is None
    assert "skipped" in result.original_state["note"]
    with duckdb.connect(":memory:") as connection:
        statements = sqlglot.parse(result.findings[0].divergence["reproducer_sql"], read="duckdb")
        for statement in statements[:2]:
            connection.execute(statement.sql(dialect="duckdb"))
        left = connection.execute(statements[2].sql(dialect="duckdb")).fetchall()
        right = connection.execute(statements[3].sql(dialect="duckdb")).fetchall()
        assert left != right


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_control_and_bounded_search_are_not_equivalence_proofs() -> None:
    result = duck(*BOUNDARY, config=CheckConfig(max_attempts=1))
    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert result.search.executed == 1
    assert "not evidence of equivalence" in result.headline


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_query_error_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("query deadline exceeded")

    monkeypatch.setattr("isitright.packs.sql.hosts._execute_duckdb", fail)
    result = duck(*BOUNDARY)
    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert "query deadline exceeded" in result.errors[0]["message"]


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_nonfinite_emulated_result_is_inconclusive() -> None:
    # float division by zero is infinity in DuckDB and an error in PostgreSQL: inconclusive
    result = check(
        engine="duckdb",
        ddl=DDL_FLOAT,
        reference_sql="SELECT collected / 0 FROM item",
        candidate_sql="SELECT collected FROM item",
    )
    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert "non-finite" in result.errors[0]["message"]


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_integer_division_by_zero_is_an_error_as_in_postgres_not_a_null() -> None:
    result = duck("SELECT amount / 0 FROM item", "SELECT amount FROM item", verify_native=False)
    assert result.divergence_status is DivergenceStatus.INCONCLUSIVE or not result.findings
    assert not result.findings  # no counterexample is built from DuckDB's NULL


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_emulation_translates_integer_division_so_both_engines_agree() -> None:
    result = duck("SELECT 5 / 2", "SELECT 2", verify_native=False)
    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert result.extensions["sql"]["integer_division"]["translated"] == 1


@pytest.mark.skipif(not HAS_DUCKDB, reason="optional DuckDB dependency not installed")
def test_cli_requires_fresh_output_directory(tmp_path: Path) -> None:
    schema, reference, candidate = (tmp_path / name for name in ("schema.sql", "r.sql", "c.sql"))
    schema.write_text(DDL, encoding="utf-8")
    reference.write_text(BOUNDARY[0], encoding="utf-8")
    candidate.write_text(BOUNDARY[1], encoding="utf-8")
    output = tmp_path / "out"
    args = [
        "sql",
        "check",
        "--engine",
        "duckdb",
        "--schema",
        str(schema),
        "--reference",
        str(reference),
        "--candidate",
        str(candidate),
        "--output-dir",
        str(output),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "(emulating PostgreSQL)" in result.output
    assert "Found a difference on a boundary state" in result.output
    assert "Reference returned: []" in result.output
    assert "Candidate returned: [[" in result.output
    assert "has not been checked on PostgreSQL" in result.output
    assert "counterexample.sql" in result.output
    report = json.loads((output / "case_report.json").read_text())
    assert report["cases"][0]["divergence_status"] == "COUNTEREXAMPLE_FOUND"
    assert report["schema_version"] == "0.5"
    assert (output / "counterexample.sql").is_file()
    assert CliRunner().invoke(app, args).exit_code == 2


def test_console_agreement_explains_bounded_search(capsys: pytest.CaptureFixture[str]) -> None:
    case = make_case(
        "c",
        DivergenceStatus.NOT_FOUND_WITHIN_BUDGET,
        search={
            "seed": 0,
            "attempts": 2,
            "valid_candidates": 2,
            "executed": 2,
            "budget": {"stopped_by": "attempts"},
        },
        execution_fidelity={"found_on": "NATIVE_ISOLATED", "engine": "postgres 18.6"},
    )
    _print_case_summary(case, Path("out"))
    output = capsys.readouterr().out
    assert "Tested 2 generated database states using native PostgreSQL 18.6" in output
    assert "No difference found in the states tested" in output
    assert "does not prove equivalence" in output
    assert "configured state limit" in output


def test_console_inconclusive_does_not_claim_agreement(capsys: pytest.CaptureFixture[str]) -> None:
    case = make_case(
        "c",
        DivergenceStatus.INCONCLUSIVE,
        (),
        errors=[{"code": "X", "message": "query timed out", "phase": "search"}],
        execution_fidelity={"found_on": "NATIVE_ISOLATED", "engine": "postgres"},
    )
    _print_case_summary(case, Path("out"))
    captured = capsys.readouterr()
    assert "comparison did not complete" in captured.out
    assert "no conclusion can be drawn" in captured.out
    assert "query timed out" in captured.err


@pytest.mark.skipif(not HAS_POSTGRES, reason="optional PostgreSQL dependencies not installed")
def test_native_postgres_agrees_on_integer_division() -> None:
    result = check(
        engine="postgres", ddl=DDL, reference_sql="SELECT 5 / 2", candidate_sql="SELECT 2"
    )
    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert result.execution_fidelity.found_on == "NATIVE_ISOLATED"
    assert result.extensions["sql"]["native_verification"] == "NATIVE_EXECUTION"
    assert result.extensions["sql"]["translation_status"] == "NOT_REQUIRED"


@pytest.mark.skipif(not HAS_POSTGRES, reason="optional PostgreSQL dependencies not installed")
def test_native_postgres_finds_and_replays_nullable_aggregate() -> None:
    with _postgres_server() as (psycopg, uri):
        result = check(
            engine="postgres",
            ddl=DDL,
            reference_sql=AGGREGATE[0],
            candidate_sql=AGGREGATE[1],
            _server=(psycopg, uri),
        )
        assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
        assert result.findings[0].mutation_path[-1].family == "missing"
        assert result.validity.tiers == ["STRUCTURAL"]
        assert result.execution_fidelity.engine.startswith("postgres ")
        statements = sqlglot.parse(result.findings[0].divergence["reproducer_sql"], read="postgres")
        with psycopg.connect(uri, autocommit=True) as connection:
            for statement in statements[:2]:
                connection.execute(statement.sql(dialect="postgres"))
            left = connection.execute(statements[2].sql(dialect="postgres")).fetchall()
            right = connection.execute(statements[3].sql(dialect="postgres")).fetchall()
            assert left != right
