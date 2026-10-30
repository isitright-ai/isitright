import importlib.util

import pytest

from isitright import SuiteCase
from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from isitright.packs.sql.models import CanonicalValueKind
from isitright.packs.sql.postgres_ddl import Schema, _render_state, parse_postgres_database_schema
from isitright.packs.sql.postgres_server import _postgres_server
from isitright.packs.sql.state import DatabaseState, TableState
from tests.pgcompat import check_postgres, check_postgres_suite, replay_postgres

HAS_DUCK = importlib.util.find_spec("duckdb") is not None
HAS_POSTGRES = all(
    importlib.util.find_spec(name) is not None for name in ("embedded_postgres", "psycopg")
)
TEXT_DDL = (
    "CREATE TABLE parent (id TEXT, PRIMARY KEY (id));"
    "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, "
    "FOREIGN KEY (parent_id) REFERENCES parent(id))"
)
REF = "SELECT p.id FROM parent p LEFT JOIN child c ON p.id = c.parent_id"
ALT = "SELECT p.id FROM parent p JOIN child c ON p.id = c.parent_id"


@pytest.mark.skipif(not HAS_DUCK, reason="DuckDB not installed")
def test_text_keys_table_constraints_and_replay() -> None:
    report = check_postgres(ddl=TEXT_DDL, reference_sql=REF, candidate_sql=ALT, engine="duckdb")
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert "key-2" in report.findings[0].divergence["reproducer_sql"]
    assert replay_postgres(report)["reproduced"]


def test_text_state_sql_roundtrip_quotes_untrusted_data() -> None:
    schema = Schema(parse_postgres_database_schema("CREATE TABLE item (id TEXT PRIMARY KEY)"))
    value = "hello'); DROP TABLE item; --"
    state = DatabaseState((TableState("item", ("id",), ((value,),)),))
    sql = _render_state(schema, state)
    assert "hello''); DROP TABLE item; --" in sql  # the quote is doubled: the value stays data


@pytest.mark.skipif(not HAS_DUCK, reason="DuckDB not installed")
def test_unique_constraint_rejections_do_not_end_search() -> None:
    ddl = "CREATE TABLE item (id TEXT PRIMARY KEY, amount INTEGER UNIQUE DEFAULT 0)"
    report = check_postgres(
        ddl=ddl,
        reference_sql="SELECT id FROM item WHERE amount > 100",
        candidate_sql="SELECT id FROM item WHERE amount >= 100",
        engine="duckdb",
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    # Copies get fresh values in UNIQUE columns, so the engine has nothing to reject here.
    assert report.search.rejected.get("engine_constraint", 0) == 0
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(not HAS_DUCK, reason="DuckDB not installed")
@pytest.mark.parametrize(
    "kind",
    [
        "SMALLINT",
        "BIGINT",
        "DECIMAL",
        "REAL",
        "DOUBLE PRECISION",
        "BOOLEAN",
        "DATE",
        "TIMESTAMP",
        "TIMESTAMPTZ",
        "UUID",
    ],
)
def test_common_types_null_behavior_and_replay(kind: str) -> None:
    ddl = f"CREATE TABLE item (id TEXT PRIMARY KEY, value {kind})"
    report = check_postgres(
        ddl=ddl,
        reference_sql="SELECT COUNT(*) FROM item",
        candidate_sql="SELECT COUNT(value) FROM item",
        engine="duckdb",
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert replay_postgres(report)["reproduced"]


@pytest.mark.skipif(not HAS_DUCK, reason="DuckDB not installed")
def test_out_of_range_candidate_is_rejected_without_masking_prior_agreement() -> None:
    report = check_postgres(
        ddl="CREATE TABLE item (id INTEGER PRIMARY KEY, value SMALLINT)",
        reference_sql="SELECT id FROM item WHERE value > 40000",
        candidate_sql="SELECT id FROM item WHERE value >= 40000",
        engine="duckdb",
    )
    assert report.divergence_status.value == "NOT_FOUND_WITHIN_BUDGET", report
    assert sum(report.search.rejected.values()) > 0


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not installed")
def test_native_common_types_and_scoped_queries() -> None:
    ddl = "CREATE TABLE item (id TEXT PRIMARY KEY, amount DECIMAL, day DATE, active BOOLEAN)"
    cases = [
        SuiteCase(
            case_id="cte",
            reference_sql="WITH q AS (SELECT id, amount FROM item) "
            "SELECT id FROM q WHERE amount > 100",
            candidate_sql="WITH q AS (SELECT id, amount FROM item) "
            "SELECT id FROM q WHERE amount >= 100",
        ),
        SuiteCase(
            case_id="null",
            reference_sql="SELECT COUNT(*) FROM item",
            candidate_sql="SELECT COUNT(day) FROM item",
        ),
        SuiteCase(
            case_id="decimal_scale",
            reference_sql="SELECT 1.0",
            candidate_sql="SELECT 1.00",
        ),
    ]
    suite = check_postgres_suite(ddl=ddl, cases=cases)
    assert {case.case_id: case.divergence_status.value for case in suite.cases} == {
        "cte": "COUNTEREXAMPLE_FOUND",
        "null": "COUNTEREXAMPLE_FOUND",
        "decimal_scale": "NOT_FOUND_WITHIN_BUDGET",
    }
    assert all(
        case.extensions["sql"]["native_verification"] == "NATIVE_EXECUTION" for case in suite.cases
    )


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not installed")
def test_native_typed_outputs_identity_and_uuid_key_replay() -> None:
    ddl = (
        "CREATE TABLE item (id UUID, amount DECIMAL, day DATE, created TIMESTAMP, "
        "enabled BOOLEAN, PRIMARY KEY (id))"
    )
    cases = [
        SuiteCase(
            case_id=name,
            reference_sql=f"SELECT {name} FROM item",
            candidate_sql=f"SELECT {name} FROM item WHERE {name} IS NULL",
        )
        for name in ("id", "amount", "day", "created", "enabled")
    ]
    suite = check_postgres_suite(ddl=ddl, cases=cases)
    found = {case.case_id: case for case in suite.cases}
    expected = {
        "id": CanonicalValueKind.ENGINE_SPECIFIC,
        "amount": CanonicalValueKind.DECIMAL,
        "day": CanonicalValueKind.DATE,
        "created": CanonicalValueKind.DATETIME,
        "enabled": CanonicalValueKind.BOOLEAN,
    }
    for name, kind in expected.items():
        report = found[name]
        assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
        assert report.findings[0].divergence["reference_result"]["rows"][0][0]["kind"] == kind.value
    assert replay_postgres(found["id"])["reproduced"]

    identity = check_postgres(
        ddl="CREATE TABLE entry (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
        "value INTEGER)",
        reference_sql="SELECT id FROM entry WHERE value > 100",
        candidate_sql="SELECT id FROM entry WHERE value >= 100",
    )
    assert identity.divergence_status.value == "COUNTEREXAMPLE_FOUND", identity


@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not installed")
def test_native_text_foreign_keys_and_serial_defaults() -> None:
    with _postgres_server() as server:
        report = check_postgres(ddl=TEXT_DDL, reference_sql=REF, candidate_sql=ALT, _server=server)
        assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
        serial = check_postgres(
            ddl="CREATE TABLE entry (id SERIAL PRIMARY KEY, amount INTEGER DEFAULT 0)",
            reference_sql="SELECT id FROM entry WHERE amount > 100",
            candidate_sql="SELECT id FROM entry WHERE amount >= 100",
            _server=server,
        )
        assert serial.divergence_status.value == "COUNTEREXAMPLE_FOUND", serial
        uuid_report = check_postgres(
            ddl=TEXT_DDL.replace("TEXT", "UUID"),
            reference_sql=REF,
            candidate_sql=ALT,
            _server=server,
        )
        assert uuid_report.divergence_status.value == "COUNTEREXAMPLE_FOUND", uuid_report
        parameterized = check_postgres(
            ddl=(
                "CREATE TABLE parent (id VARCHAR(20) PRIMARY KEY);"
                "CREATE TABLE child (id VARCHAR(5) PRIMARY KEY, "
                "parent_id VARCHAR(1) REFERENCES parent(id), amount NUMERIC(2, 2))"
            ),
            reference_sql=REF,
            candidate_sql=ALT,
            _server=server,
        )
        assert parameterized.divergence_status.value == "COUNTEREXAMPLE_FOUND", parameterized
        small = check_postgres(
            ddl="CREATE TABLE item (id INTEGER PRIMARY KEY, value SMALLINT)",
            reference_sql="SELECT id FROM item WHERE value > 40000",
            candidate_sql="SELECT id FROM item WHERE value >= 40000",
            _server=server,
        )
        assert small.divergence_status.value == "NOT_FOUND_WITHIN_BUDGET", small
        assert sum(small.search.rejected.values()) > 0
    assert replay_postgres(report)["reproduced"]
    assert replay_postgres(uuid_report)["reproduced"]
    assert replay_postgres(parameterized)["reproduced"]


def test_table_level_unique_and_literal_default_are_retained() -> None:
    schema = parse_postgres_database_schema(
        "CREATE TABLE item (id TEXT, value INTEGER DEFAULT -1, PRIMARY KEY (id), UNIQUE (value))"
    )
    table = schema.table("item")
    assert table.unique_columns == (("value",),)
    assert table.columns[1].default_sql == "-1"


@pytest.mark.skipif(not HAS_DUCK, reason="DuckDB not installed")
def test_parameterized_types_and_differently_sized_text_foreign_keys() -> None:
    ddl = (
        "CREATE TABLE parent (id VARCHAR(20) PRIMARY KEY);"
        "CREATE TABLE child (id VARCHAR(5) PRIMARY KEY, "
        "parent_id VARCHAR(1) REFERENCES parent(id), amount NUMERIC(2, 2))"
    )
    report = check_postgres(ddl=ddl, reference_sql=REF, candidate_sql=ALT, engine="duckdb")
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND", report
    assert replay_postgres(report)["reproduced"]
    numeric = check_postgres(
        ddl="CREATE TABLE item (id VARCHAR(1) PRIMARY KEY, value NUMERIC(2,2))",
        reference_sql="SELECT id FROM item WHERE value > 0",
        candidate_sql="SELECT id FROM item WHERE value >= 0",
        engine="duckdb",
    )
    assert numeric.divergence_status.value == "COUNTEREXAMPLE_FOUND", numeric
    assert replay_postgres(numeric)["reproduced"]


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE item (id TEXT, value INTEGER, PRIMARY KEY (id, value))",
        "CREATE TABLE item (id TEXT PRIMARY KEY, value NUMERIC(0, 2))",
        "CREATE TABLE item (id TEXT PRIMARY KEY, value TEXT DEFAULT current_user)",
        "CREATE TABLE item (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY)",
    ],
)
def test_unsupported_schema_constructs_fail_closed(ddl: str) -> None:
    with pytest.raises(PostgresInputError):
        parse_postgres_database_schema(ddl)
