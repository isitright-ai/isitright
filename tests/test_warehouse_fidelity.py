"""Run the dialect fidelity fixtures on the DuckDB emulation and check them against the docs."""

from __future__ import annotations

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
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
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


def _plain(result: QueryResult) -> list[list[Any]]:
    return [[cell.value for cell in row] for row in result.rows]


def _normal(outcome: Any, ordered: bool) -> Any:
    if isinstance(outcome, list) and not ordered:
        return sorted(outcome, key=repr)
    return outcome


def _host(fixture: Fixture) -> tuple[Any, DuckdbHost, Any]:
    ddl, rows = SETUP[fixture.dialect]
    dialect = get_dialect(fixture.dialect)
    db = parse_warehouse_schema(ddl, dialect)
    state = _state(build_model(db, dialect.name), rows)
    return db, DuckdbHost(Schema(db), dialect), state


def _execute(host: DuckdbHost, state: Any, sql: str) -> Any:
    try:
        left, _ = host.run_pair(state, sql, sql, timeout_seconds=10, max_result_rows=100)
    except QueryExecutionError:
        return ERROR
    return _plain(left)


def _emulated(fixture: Fixture) -> Any:
    db, host, state = _host(fixture)
    dialect = get_dialect(fixture.dialect)
    try:
        translated = to_duckdb(resolve_tables(parse_query(fixture.query, dialect), db), dialect, db)
    except SqlInputError as error:
        assert fixture.status == "detected", str(error)
        assert fixture.detected_text in str(error)
        return "REJECTED"
    return _execute(host, state, translated.sql)


def _raw(fixture: Fixture) -> Any:
    """What a plain SQLGlot transpile would have run (no rewrite, no check)."""
    _, host, state = _host(fixture)
    dialect = get_dialect(fixture.dialect)
    text = sqlglot.transpile(fixture.query, read=dialect.read, write="duckdb")[0]
    try:
        return _execute(host, state, text)
    except Exception as error:  # a raw text DuckDB cannot even run is not the documented outcome
        return f"RAW-ERROR {type(error).__name__}"


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
    # BigQuery: the owner's smoke test (2026-11-07); Presto: a local Trino 484 (2026-11-08)
    assert fixture.confirmed


@pytest.mark.parametrize(
    "fixture",
    [
        f
        for f in FIXTURES
        if f.status in ("agrees", "translated", "checked") and f.native is not None
    ],
    ids=lambda f: f.id,
)
def test_translated_means_a_plain_transpile_would_have_differed(fixture: Fixture) -> None:
    raw = _normal(_raw(fixture), fixture.ordered)
    native = _normal(fixture.native, fixture.ordered)
    if fixture.status == "translated" and "state_does_not_discriminate" in fixture.extra:
        assert raw == native  # true here only because of the state; REVIEW lists these
    elif fixture.status == "translated":
        assert raw != native, "the rewrite is not needed: mark the fixture 'agrees'"
    else:  # agrees, or checked by the result rules that every route shares
        assert raw == native, "a rewrite changes this fixture: mark it 'translated'"


def test_every_fixture_has_a_status_and_a_source() -> None:
    assert {f.status for f in FIXTURES} <= {"agrees", "translated", "checked", "detected", "listed"}
    assert all(f.source for f in FIXTURES)
    assert len({f.id for f in FIXTURES}) == len(FIXTURES)
    assert {f.dialect for f in FIXTURES} == {"bigquery", "presto"}
