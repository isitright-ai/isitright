"""Native confirmation hosts against fakes. A fake cannot test BigQuery's or Trino's semantics:
these tests cover the guard that refuses real tables, the dry-run-then-run order, the cap on
billed bytes, labels, the confirmation records, and that credentials never reach a report."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import BigQueryHost, ConnectionHost, TrinoHost, check
from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.inline import RealTableReference, assert_inline_only, inline_sql
from isitright.packs.sql.native import NativeHostError, load_connection
from isitright.packs.sql.state import DatabaseState, TableState
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables

# Proposed fixture: pending owner review (constructed schema and queries, written by Claude).
BQ_DDL = "CREATE TABLE `proj.shop.items` (id INT64 NOT NULL, tags ARRAY<INT64>, name STRING)"
BQ_LEFT = "SELECT t.id, tag FROM `proj.shop.items` AS t LEFT JOIN UNNEST(t.tags) AS tag"
BQ_CROSS = "SELECT t.id, tag FROM `proj.shop.items` AS t CROSS JOIN UNNEST(t.tags) AS tag"
BQ = get_dialect("bigquery")
PRESTO = get_dialect("presto")


class FakeJob:
    def __init__(self, estimate: int = 0, names: Any = (), rows: Any = ()) -> None:
        self.total_bytes_processed = estimate
        self.total_bytes_billed = 0
        self.job_id = "job-1"
        self.schema = [
            SimpleNamespace(name=n, field_type="INTEGER", mode="NULLABLE") for n in names
        ]
        self._rows = list(rows)

    def result(self, timeout: Any = None, max_results: Any = None) -> list[Any]:
        return self._rows


class FakeClient:
    """Records every query; the answer comes from ``respond(sql) -> (names, rows)``."""

    def __init__(self, respond: Any = None, estimate: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.respond = respond or (lambda sql: (["a"], [(1,)]))
        self.estimate = estimate

    def query(self, sql: str, job_config: dict[str, Any], location: Any = None) -> FakeJob:
        self.calls.append((sql, job_config))
        if job_config.get("dry_run"):
            return FakeJob(estimate=self.estimate)
        names, rows = self.respond(sql)
        return FakeJob(names=names, rows=rows)


def _host(client: FakeClient, **kwargs: Any) -> BigQueryHost:
    return BigQueryHost(client_factory=lambda: client, config_factory=lambda **kw: kw, **kwargs)


def _left_or_cross(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    return (["id", "tag"], [(10, None)]) if "LEFT JOIN" in sql else (["id", "tag"], [])


# --- the guard ------------------------------------------------------------------------------------


def _inline_for(dialect_name: str, ddl: str, sql: str) -> tuple[str, str]:
    dialect = get_dialect(dialect_name)
    db = parse_warehouse_schema(ddl, dialect)
    tree = resolve_tables(parse_query(sql, dialect), db)
    cols = tuple(c.name for c in db.tables[0].columns)
    state = DatabaseState((TableState(db.tables[0].name, cols, ()),))
    return inline_sql(tree, dialect, db, state), sql


@pytest.mark.parametrize(
    ("dialect", "ddl", "sql"),
    [
        ("bigquery", BQ_DDL, BQ_LEFT),
        ("presto", "CREATE TABLE items (id bigint, tags array(bigint))", "SELECT id FROM items"),
    ],
)
def test_inline_text_passes_the_guard_and_the_original_does_not(
    dialect: str, ddl: str, sql: str
) -> None:
    inline, original = _inline_for(dialect, ddl, sql)
    assert_inline_only(inline, get_dialect(dialect))
    with pytest.raises(RealTableReference):
        assert_inline_only(original, get_dialect(dialect))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM `proj.shop.items`",
        "SELECT * FROM (SELECT * FROM UNNEST([1])) AS a WHERE a IN (SELECT id FROM shop.items)",
        "SELECT 1 UNION ALL SELECT id FROM items",
        "SELECT * FROM UNNEST([1]) AS a JOIN `p.d.items_view` AS v ON TRUE",
        "WITH items AS (SELECT 1 AS id) SELECT * FROM items JOIN real_table ON TRUE",
        "SELECT * FROM INFORMATION_SCHEMA.TABLES",
        "SELECT (SELECT COUNT(*) FROM events) AS n",
    ],
)
def test_the_guard_refuses_any_text_that_still_names_a_table(sql: str) -> None:
    with pytest.raises(RealTableReference):
        assert_inline_only(sql, BQ)


def test_the_guard_accepts_a_cte_and_refuses_other_statements() -> None:
    assert_inline_only("WITH a AS (SELECT 1 AS x) SELECT x FROM a", BQ)
    with pytest.raises(RealTableReference):
        assert_inline_only("DELETE FROM t WHERE TRUE", BQ)
    with pytest.raises(RealTableReference):
        assert_inline_only("SELECT 1; SELECT 2", BQ)


# --- BigQuery host --------------------------------------------------------------------------------


def test_bigquery_host_dry_runs_first_then_runs_with_a_cap_and_labels() -> None:
    client = FakeClient()
    host = _host(client, max_bytes_billed=12345)
    inline, _ = _inline_for("bigquery", BQ_DDL, BQ_LEFT)
    result = host.run_inline(inline, BQ, timeout_seconds=5, max_rows=100)
    assert [c.name for c in result.columns] == ["a"]
    assert len(client.calls) == 2
    (dry_sql, dry), (run_sql, run) = client.calls
    assert dry["dry_run"] is True and "maximum_bytes_billed" not in dry
    assert run["maximum_bytes_billed"] == 12345 and not run.get("dry_run")
    assert dry_sql == run_sql == inline
    for config in (dry, run):
        assert config["labels"]["isitright"] == "1"
        assert config["labels"]["isitright_phase"] == "confirm"
        assert config["use_query_cache"] is False
    assert [r["phase"] for r in host.records] == ["dry_run", "run"]


def test_bigquery_host_refuses_a_real_table_before_any_client_call() -> None:
    client = FakeClient()
    host = _host(client)
    with pytest.raises(RealTableReference):
        host.run_inline(BQ_LEFT, BQ, timeout_seconds=5, max_rows=10)
    assert client.calls == []


def test_a_dry_run_estimate_above_the_bound_stops_before_the_real_run() -> None:
    client = FakeClient(estimate=5 * 1024**3)
    host = _host(client)
    inline, _ = _inline_for("bigquery", BQ_DDL, BQ_LEFT)
    with pytest.raises(NativeHostError, match="dry run"):
        host.run_inline(inline, BQ, timeout_seconds=5, max_rows=10)
    assert len(client.calls) == 1 and client.calls[0][1]["dry_run"] is True


def test_a_query_over_the_length_limit_is_not_sent() -> None:
    client = FakeClient()
    host = _host(client)
    long_query = "SELECT " + " + ".join(["1"] * 400_000)
    with pytest.raises(NativeHostError, match="characters"):
        host.run_inline(long_query, BQ, timeout_seconds=5, max_rows=10)
    assert client.calls == []


def test_an_array_with_a_null_element_in_a_native_result_is_a_query_error() -> None:
    client = FakeClient(respond=lambda sql: (["a"], [([1, None],)]))
    host = _host(client)
    with pytest.raises(Exception, match="NULL elements"):
        host.run_inline("SELECT [1] AS a", BQ, timeout_seconds=5, max_rows=10)


# --- the confirmation flow ------------------------------------------------------------------------


def _audit(client: FakeClient | None, **kwargs: Any) -> Any:
    host = _host(client) if client is not None else None
    return check(
        reference_sql=BQ_LEFT,
        candidate_sql=BQ_CROSS,
        dialect="bigquery",
        ddl=BQ_DDL,
        confirm=host,
        **kwargs,
    )


def test_a_finding_confirmed_natively_is_verified_on_native_inline() -> None:
    client = FakeClient(respond=_left_or_cross)
    report = _audit(client)
    finding = report.findings[0]
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert finding.fidelity.found_on == "EMULATED"
    assert finding.fidelity.verified_on == "NATIVE_INLINE"
    assert finding.fidelity.verification.status == "VERIFIED"  # type: ignore[union-attr]
    assert finding.divergence["native_confirmation"][0]["world"] == "minimized"
    assert "native_results" in finding.divergence
    assert report.extensions["sql"]["native_verification"] == "NATIVE_VERIFIED"
    # two queries per confirmation, each a dry run then a run, and nothing but inline text
    assert len(client.calls) == 4
    for sql, _ in client.calls:
        assert_inline_only(sql, BQ)
        assert "proj.shop.items" not in sql and "`items`" not in sql


def test_a_divergence_that_does_not_reproduce_natively_is_an_emulation_artifact() -> None:
    client = FakeClient(respond=lambda sql: (["id", "tag"], []))  # both sides agree natively
    report = _audit(client)
    assert report.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert report.findings == []
    sql = report.extensions["sql"]
    assert (
        sql["emulation_artifact_count"] == 1 and sql["native_verification"] == "ARTIFACTS_EXCLUDED"
    )
    artifact = sql["emulation_artifacts"][0]
    assert artifact["native_confirmation"][0]["world"] == "minimized"
    assert artifact["reproducer_sql"]


def test_the_unminimized_world_is_tried_when_the_minimized_one_does_not_reproduce() -> None:
    calls = {"n": 0}

    def run(sql: str) -> tuple[list[str], list[list[Any]]]:
        if "LEFT JOIN" in sql:
            calls["n"] += 1
            return ["id", "tag"], ([[10, None]] if calls["n"] > 1 else [])
        return ["id", "tag"], []

    report = check(
        reference_sql="SELECT t.id, tag FROM items AS t LEFT JOIN UNNEST(t.tags) AS u(tag) ON TRUE",
        candidate_sql="SELECT t.id, tag FROM items AS t CROSS JOIN UNNEST(t.tags) AS u(tag)",
        dialect="presto",
        ddl="CREATE TABLE web.items (id bigint, tags array(bigint), name varchar)",
        confirm=ConnectionHost(run=run),
    )
    finding = report.findings[0]
    results = [a["result"] for a in finding.divergence["native_confirmation"]]
    assert results == ["agree", "differ"]
    assert finding.fidelity.verified_on == "NATIVE_INLINE"


def test_a_world_that_minimization_did_not_change_is_confirmed_once() -> None:
    client = FakeClient(respond=lambda sql: (["id", "tag"], []))
    report = _audit(client)
    artifact = report.extensions["sql"]["emulation_artifacts"][0]
    assert [a["world"] for a in artifact["native_confirmation"]] == ["minimized"]


def test_without_a_native_host_the_finding_is_not_verified_and_says_why() -> None:
    report = _audit(None)
    finding = report.findings[0]
    assert finding.fidelity.verified_on is None
    assert finding.fidelity.verification.status == "NOT_VERIFIED"  # type: ignore[union-attr]
    assert "no native host" in finding.fidelity.verification.note  # type: ignore[union-attr]
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND


def test_a_native_failure_leaves_the_finding_unverified_with_the_reason() -> None:
    def broken(sql: str) -> Any:
        raise RuntimeError("boom")

    report = _audit(FakeClient(respond=broken))
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "NOT_VERIFIED"
    assert "native run failed" in verification.note


def test_the_search_never_runs_on_the_native_host() -> None:
    client = FakeClient(respond=_left_or_cross)
    _audit(client)
    # only the finding's worlds were sent: a handful of queries, not the 500 attempts
    assert len(client.calls) <= 8


# --- credentials ----------------------------------------------------------------------------------


def test_credentials_never_reach_a_report_or_a_host_record(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SECRET-KEY-PATH-0123456789"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", secret)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", secret + "-project")
    client = FakeClient(respond=_left_or_cross)
    host = _host(client)
    report = check(
        reference_sql=BQ_LEFT,
        candidate_sql=BQ_CROSS,
        dialect="bigquery",
        ddl=BQ_DDL,
        confirm=host,
    )
    dumped = json.dumps(report.model_dump(mode="json")) + json.dumps(host.records)
    dumped += "".join(sql for sql, _ in client.calls) + json.dumps([c for _, c in client.calls])
    assert secret not in dumped


def test_the_env_file_reader_sets_only_the_named_variable(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isitright.packs.sql.native import load_env_file

    monkeypatch.delenv("WANTED_VAR", raising=False)
    monkeypatch.delenv("OTHER_VAR", raising=False)
    path = tmp_path / "x.env"
    path.write_text("# c\nWANTED_VAR=abc\nOTHER_VAR=def\n", encoding="utf-8")
    load_env_file(path, ["WANTED_VAR"])
    import os

    assert os.environ["WANTED_VAR"] == "abc" and "OTHER_VAR" not in os.environ
    monkeypatch.delenv("WANTED_VAR", raising=False)


# --- bring your own connection and Trino ----------------------------------------------------------


def fake_run(sql: str) -> tuple[list[str], list[list[Any]]]:
    """A stand-in for a user's function: this one answers LEFT JOIN with a NULL row."""
    return ["id", "tag"], ([[10, None]] if "LEFT JOIN" in sql else [])


def test_connection_host_runs_only_inline_text_and_canonicalizes_rows() -> None:
    seen: list[str] = []

    def run(sql: str) -> tuple[list[str], list[list[Any]]]:
        seen.append(sql)
        return fake_run(sql)

    host = ConnectionHost(run=run)
    report = check(
        reference_sql=BQ_LEFT, candidate_sql=BQ_CROSS, dialect="bigquery", ddl=BQ_DDL, confirm=host
    )
    assert report.findings[0].fidelity.verified_on == "NATIVE_INLINE"
    assert report.findings[0].fidelity.verification.engine == "connection"  # type: ignore[union-attr]
    for sql in seen:
        assert_inline_only(sql, BQ)
    with pytest.raises(RealTableReference):
        host.run_inline(BQ_LEFT, BQ, timeout_seconds=1, max_rows=5)
    assert len(seen) == 2  # the refused text was never passed to the function


def test_connection_host_times_out_and_reports_function_errors() -> None:
    inline, _ = _inline_for("bigquery", BQ_DDL, BQ_LEFT)

    def slow(sql: str) -> tuple[list[str], list[list[Any]]]:
        time.sleep(2)
        return [], []

    with pytest.raises(NativeHostError, match="did not return"):
        ConnectionHost(run=slow).run_inline(inline, BQ, timeout_seconds=0.1, max_rows=5)

    def failing(sql: str) -> tuple[list[str], list[list[Any]]]:
        raise ValueError("engine says no")

    with pytest.raises(Exception, match="engine says no"):
        ConnectionHost(run=failing).run_inline(inline, BQ, timeout_seconds=2, max_rows=5)


def test_a_connection_function_is_loaded_from_module_and_name() -> None:
    func = load_connection("tests.test_warehouse_hosts:fake_run")
    assert func("LEFT JOIN")[1] == [[10, None]]
    for bad in ("nocolon", "tests.test_warehouse_hosts:missing", "no_such_module_x:f"):
        with pytest.raises(SqlInputError):
            load_connection(bad)


def test_trino_host_uses_the_supplied_connection_and_the_guard() -> None:
    class Cursor:
        description = [("id", "bigint"), ("tag", "bigint")]  # noqa: RUF012

        def execute(self, sql: str) -> None:
            self.sql = sql

        def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
            return [(10, None)] if "LEFT JOIN" in self.sql else []

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    ddl = "CREATE TABLE web.items (id bigint, tags array(bigint))"
    left = "SELECT t.id, tag FROM items AS t LEFT JOIN UNNEST(t.tags) AS u(tag) ON TRUE"
    cross = "SELECT t.id, tag FROM items AS t CROSS JOIN UNNEST(t.tags) AS u(tag)"
    report = check(
        reference_sql=left,
        candidate_sql=cross,
        dialect="trino",
        ddl=ddl,
        confirm=TrinoHost(connect=Connection),
    )
    assert report.findings[0].fidelity.verified_on == "NATIVE_INLINE"
    with pytest.raises(RealTableReference):
        TrinoHost(connect=Connection).run_inline(left, PRESTO, timeout_seconds=1, max_rows=5)
