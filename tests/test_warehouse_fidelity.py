"""Run the dialect fidelity fixtures on the DuckDB emulation and check them against the docs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("duckdb")

import sqlglot

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.hosts import DuckdbHost
from isitright.packs.sql.mapping import build_model
from isitright.packs.sql.models import QueryResult
from isitright.packs.sql.postgres_ddl import Schema
from isitright.packs.sql.replaying import _state
from isitright.packs.sql.sqlite_sandbox import (
    QueryDataError,
    QueryExecutionError,
    QueryResourceLimitError,
    QueryTimeoutError,
)
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables, to_duckdb
from tests.warehouse_fixtures import (
    BQ_DDL,
    BQ_ROWS,
    ERROR,
    FIXTURES,
    PRESTO_DDL,
    PRESTO_ROWS,
    Fixture,
)

COMPARED = ("agrees", "translated", "checked")
SETUP = {"bigquery": (BQ_DDL, BQ_ROWS), "presto": (PRESTO_DDL, PRESTO_ROWS)}
OBSERVATIONS = Path(__file__).with_name("warehouse_native_observations.json")


def _plain(result: QueryResult) -> list[list[Any]]:
    return [[cell.value for cell in row] for row in result.rows]


def _normal(outcome: Any, ordered: bool) -> Any:
    if isinstance(outcome, list) and not ordered:
        return sorted(outcome, key=repr)
    return outcome


def _host(fixture: Fixture, *, raw: bool = False) -> tuple[Any, DuckdbHost, Any]:
    """``raw``: what a plain transpile would meet, with none of the pack's result rules and, where
    the fixture says so, a session in another time zone (the machine's, not UTC)."""
    ddl, rows = SETUP[fixture.dialect]
    dialect = get_dialect(fixture.dialect)
    db = parse_warehouse_schema(ddl, dialect)
    state = _state(build_model(db, dialect.name), rows)
    zone = str(fixture.extra.get("raw_session_time_zone", "UTC")) if raw else "UTC"
    return db, DuckdbHost(Schema(db), dialect, time_zone=zone, result_rules=not raw), state


def _run(
    host: DuckdbHost, state: Any, sql: str
) -> tuple[Any, QueryExecutionError | None, QueryResult | None]:
    """The outcome, the error and the result. Only a query error counts as ``ERROR``; any other
    failure (a bug, a connection) propagates and fails the test."""
    try:
        left, _ = host.run_pair(state, sql, sql, timeout_seconds=10, max_result_rows=100)
    except QueryExecutionError as error:
        return ERROR, error, None
    return _plain(left), None, left


def _execute(host: DuckdbHost, state: Any, sql: str) -> Any:
    return _run(host, state, sql)[0]


def expect_data_error(fixture: Fixture, error: QueryExecutionError | None) -> None:
    """An expected ``ERROR`` must be the data error the fixture names: a ``QueryDataError`` (not a
    timeout, a row limit, a parse or bind error, all ``QueryExecutionError`` too) whose message
    carries the fixture's ``error_text``."""
    assert fixture.error_text, f"{fixture.id}: name the expected error text"
    assert isinstance(error, QueryDataError), f"{fixture.id}: {type(error).__name__}: {error}"
    assert fixture.error_text.lower() in str(error).lower(), str(error)


def _emulated_run(fixture: Fixture) -> tuple[Any, QueryExecutionError | None, QueryResult | None]:
    db, host, state = _host(fixture)
    dialect = get_dialect(fixture.dialect)
    try:
        translated = to_duckdb(resolve_tables(parse_query(fixture.query, dialect), db), dialect, db)
    except SqlInputError as error:
        assert fixture.status == "detected", str(error)
        assert fixture.detected_text in str(error)
        return "REJECTED", None, None
    return _run(host, state, translated.sql)


def _emulated(fixture: Fixture) -> Any:
    outcome, error, _ = _emulated_run(fixture)
    if fixture.emulated == ERROR and outcome == ERROR:
        expect_data_error(fixture, error)  # not an unrelated failure that also raises
    return outcome


ERROR_FIXTURES = [f for f in FIXTURES if f.emulated == ERROR]


@pytest.mark.parametrize("fixture", ERROR_FIXTURES, ids=lambda f: f.id)
@pytest.mark.parametrize(
    "kind",
    [QueryTimeoutError, QueryResourceLimitError, QueryExecutionError],
    ids=["timeout", "row-limit", "parse-or-bind"],
)
def test_another_failure_cannot_pass_as_the_expected_data_error(
    fixture: Fixture, kind: type[QueryExecutionError]
) -> None:
    """Even with the expected words in its message, a timeout, a row limit or a parse or bind
    error is not the fixture's data error."""
    impostor = kind(f"{fixture.error_text} (but a {kind.__name__})")
    with pytest.raises(AssertionError, match=kind.__name__):
        expect_data_error(fixture, impostor)
    expect_data_error(fixture, QueryDataError(f"{fixture.error_text}"))  # the real category


def _raw(fixture: Fixture) -> Any:
    """What a plain SQLGlot transpile would have run: no rewrite, none of the pack's result rules,
    and the session zone the fixture names (the machine's zone, not UTC)."""
    _, host, state = _host(fixture, raw=True)
    dialect = get_dialect(fixture.dialect)
    text = sqlglot.transpile(fixture.query, read=dialect.read, write="duckdb")[0]
    try:
        return _execute(host, state, text)
    except RuntimeError as error:
        # DuckDB returned infinity or NaN, which a result cannot hold: not the native error
        assert "non-finite" in str(error), str(error)
        return "NON-FINITE"


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.id for f in FIXTURES])
def test_the_emulated_outcome_is_the_recorded_one(fixture: Fixture) -> None:
    assert _normal(_emulated(fixture), fixture.ordered) == _normal(
        fixture.emulated, fixture.ordered
    )


@pytest.mark.parametrize(
    "fixture",
    [
        f
        for f in FIXTURES
        if f.status in ("agrees", "translated", "checked") and f.native is not None
    ],
    ids=lambda f: f.id,
)
def test_the_emulation_matches_the_documented_native_outcome(fixture: Fixture) -> None:
    assert _normal(fixture.emulated, fixture.ordered) == _normal(fixture.native, fixture.ordered)
    # BigQuery: the owner's smoke test (2026-11-07); Presto: a local Trino 484 (2026-11-08, 09)
    assert fixture.confirmed or fixture.extra.get("unconfirmed"), "say why it is not confirmed"


@pytest.mark.parametrize(
    "fixture",
    [
        f
        for f in FIXTURES
        if f.status in ("agrees", "translated", "checked") and f.native is not None
    ],
    ids=lambda f: f.id,
)
def test_a_rewrite_or_a_rule_is_needed_exactly_where_the_status_says(fixture: Fixture) -> None:
    raw = _normal(_raw(fixture), fixture.ordered)
    native = _normal(fixture.native, fixture.ordered)
    if fixture.status == "translated":
        assert raw != native, "the rewrite is not needed: mark the fixture 'agrees'"
    elif fixture.status == "checked":
        assert raw != native, "the result rule is not needed: mark the fixture 'agrees'"
    else:
        assert raw == native, "a rewrite or a rule changes this fixture: mark it so"


@pytest.mark.parametrize(
    "fixture", [f for f in FIXTURES if f.types is not None], ids=lambda f: f.id
)
def test_the_result_type_is_the_documented_one(fixture: Fixture) -> None:
    outcome, _, result = _emulated_run(fixture)
    assert result is not None, outcome
    assert tuple(cell.kind.value for cell in result.rows[0]) == fixture.types


@pytest.mark.parametrize(
    "fixture", [f for f in FIXTURES if f.status == "listed"], ids=lambda f: f.id
)
def test_a_listed_divergence_stays_a_divergence_and_is_counted(fixture: Fixture) -> None:
    """A listed divergence is neither translated nor rejected: the emulation differs from the
    documented native outcome."""
    assert _normal(_emulated(fixture), fixture.ordered) == _normal(
        fixture.emulated, fixture.ordered
    )
    assert _normal(fixture.emulated, fixture.ordered) != _normal(fixture.native, fixture.ordered)


CONFIRMED_ON = {"bigquery": "bigquery", "presto": "trino"}
"""The engine whose record backs ``confirmed=True`` for each dialect family."""


def test_a_confirmed_fixture_matches_its_recorded_native_observation() -> None:
    """``confirmed=True`` is a claim; the observation file holds what the engine returned, its
    version and the date, one record per fixture and engine. Every confirmed fixture needs the
    record of the engine that confirms its family (BigQuery; Trino for Presto, 0.9 removed the
    exemption that let a BigQuery fixture be confirmed without one). A record of another engine
    (PrestoDB, through a connection) is checked against that engine's stated outcome, if the
    fixture states one, else against ``native``."""
    records = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))["records"]
    by_key = {(r["id"], r["engine"]): r for r in records}
    assert len(by_key) == len(records), "one record per fixture and engine"
    assert {r["id"] for r in records} <= {f.id for f in FIXTURES}
    for fixture in FIXTURES:
        mine = {engine: r for (fid, engine), r in by_key.items() if fid == fixture.id}
        if not fixture.confirmed:
            assert not mine, f"{fixture.id} has a record but is not confirmed"
            continue
        assert CONFIRMED_ON[fixture.dialect] in mine, f"{fixture.id} is confirmed without a record"
        for engine, record in mine.items():
            expected = fixture.extra.get(f"native_{engine}", fixture.native)
            assert record["engine_version"] and record["date"]
            assert _normal(record["observed"], fixture.ordered) == _normal(
                expected, fixture.ordered
            ), (fixture.id, engine)
            if expected == ERROR and fixture.native_error:
                assert fixture.native_error in record["error"], (fixture.id, engine)


def test_every_fixture_has_a_status_and_a_source() -> None:
    assert {f.status for f in FIXTURES} <= {"agrees", "translated", "checked", "detected", "listed"}
    assert all(f.source for f in FIXTURES)
    assert len({f.id for f in FIXTURES}) == len(FIXTURES)
    assert {f.dialect for f in FIXTURES} == {"bigquery", "presto"}
