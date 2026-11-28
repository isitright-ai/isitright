# Proposed fixture: pending owner review (a fake connection written by Claude; not PrestoDB).
"""The PrestoDB fixture run through a bring-your-own connection, on a fake: what is sent, how
outcomes are recorded, and that an unreachable engine stops the run instead of counting."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.inline import assert_inline_only
from isitright.packs.sql.native import ConnectionHost, NativeHostError
from tests.warehouse_fixtures import ERROR, FIXTURES

SCRIPT = Path(__file__).parents[1] / "examples" / "sql" / "prestodb" / "smoke.py"
spec = importlib.util.spec_from_file_location("prestodb_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

PRESTO = [f for f in FIXTURES if f.dialect == "presto" and f.status != "detected"]


class Recorded:
    """Answers each fixture, in order, with what Trino returned for it (as a stand-in for an
    engine that agrees with Trino), after checking that the text it is given reads no table."""

    def __init__(self, wrong: str = "") -> None:
        self.answers = iter(PRESTO)
        self.sent: list[str] = []
        self.wrong = wrong

    def __call__(self, sql: str) -> tuple[list[str], list[list[Any]]]:
        assert_inline_only(sql, get_dialect("presto"))
        self.sent.append(sql)
        fixture = next(self.answers)
        if fixture.native == ERROR:
            raise RuntimeError(f"PrestoQueryError: {fixture.native_error}")
        rows = fixture.native if fixture.native is not None else fixture.emulated
        if fixture.id == self.wrong:
            rows = [["something else"]]
        return [f"c{i}" for i in range(len(rows[0]) if rows else 0)], rows


def test_every_presto_fixture_is_sent_inline_and_recorded() -> None:
    connection = Recorded()
    rows = smoke.run_fixtures(ConnectionHost(run=connection))
    assert [r["id"] for r in rows] == [f.id for f in PRESTO] and len(connection.sent) == len(PRESTO)
    outcomes = {r["id"]: r["outcome"] for r in rows}
    assert set(outcomes.values()) <= {"confirmed", "no recorded outcome"}
    errors = [r for r in rows if r["observed_native"] == ERROR]
    assert errors and all("PrestoQueryError" in r["detail"] for r in errors)


def test_a_different_answer_is_reported_as_a_difference() -> None:
    target = next(f.id for f in PRESTO if f.native not in (None, ERROR))
    rows = smoke.run_fixtures(ConnectionHost(run=Recorded(wrong=target)))
    assert {r["id"]: r["outcome"] for r in rows}[target] == "DIFFERS"


def test_an_engine_that_cannot_be_reached_stops_the_run() -> None:
    def unreachable(sql: str) -> tuple[list[str], list[list[Any]]]:
        raise ConnectionError("connection refused")

    with pytest.raises(NativeHostError, match="connection refused"):
        smoke.run_fixtures(ConnectionHost(run=unreachable))


def test_merging_keeps_other_engines_records(tmp_path: Path) -> None:
    book = tmp_path / "observations.json"
    trino = {
        "id": PRESTO[0].id,
        "engine": "trino",
        "engine_version": "484",
        "date": "2026-11-09",
        "observed": [[1]],
        "error": "",
    }
    book.write_text(json.dumps({"note": "x", "records": [trino]}), encoding="utf-8")
    rows = [{"id": PRESTO[0].id, "observed_native": ERROR, "detail": "PrestoQueryError: X"}]
    smoke.merge_observations(book, rows, "0.289", "2026-11-13")
    merged = json.loads(book.read_text(encoding="utf-8"))["records"]
    assert trino in merged
    assert {
        "id": PRESTO[0].id,
        "engine": "prestodb",
        "engine_version": "0.289",
        "date": "2026-11-13",
        "observed": ERROR,
        "error": "PrestoQueryError: X",
    } in merged


def test_the_script_refuses_a_connection_without_trust_code(tmp_path: Path, capsys: Any) -> None:
    code = smoke.main(
        [str(tmp_path / "out.json"), "--connection", "os:getcwd", "--engine-version", "x"]
    )
    assert code == 2 and "without --trust-code" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()
