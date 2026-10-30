import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from isitright import CheckConfig, check, check_suite
from isitright.cli import app


def test_sqlite_suite_reports_candidates_before_suite_returns(tmp_path: Path) -> None:
    database = tmp_path / "test.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER);"
            "INSERT INTO item VALUES (1, 1);"
        )
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "case_id": "boundary",
                "reference_sql": "SELECT id FROM item WHERE amount > 10",
                "candidate_sql": "SELECT id FROM item WHERE amount >= 10",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    observed: list[tuple[str, str]] = []
    result = check_suite(
        database=database,
        cases=cases,
        config=CheckConfig(minimization_max_attempts=1),
        _progress=lambda case, event: observed.append((case, event)),
    )
    assert result.cases[0].case_id == "boundary"
    assert ("boundary", "counterexample") in observed
    cli = CliRunner().invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert cli.exit_code == 0, cli.output
    assert "Live candidate states:" in cli.output
    assert "boundary:" in cli.output


def test_postgres_candidate_callback_runs_before_next_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("duckdb")
    import isitright.packs.sql.hosts as hosts

    events: list[str] = []
    original = hosts._execute_duckdb
    calls = 0

    def execute(*args: object, **kwargs: object):
        nonlocal calls
        # Searching: each candidate is reported before the next one runs. After the
        # counterexample, the finding is re-executed for its evidence without progress events.
        if calls and "counterexample" not in events:
            assert len(events) == calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(hosts, "_execute_duckdb", execute)
    result = check(
        ddl="CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER)",
        reference_sql="SELECT id FROM item WHERE amount > 100",
        candidate_sql="SELECT id FROM item WHERE amount >= 100",
        engine="duckdb",
        _progress=events.append,
    )
    assert result.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert events[-1] == "counterexample"
    assert calls >= len(events)


def test_postgres_progress_reports_rejected_states_and_execution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("duckdb")
    import isitright.packs.sql.hosts as hosts

    options = {
        "ddl": "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER)",
        "reference_sql": "SELECT id FROM item",
        "candidate_sql": "SELECT id FROM item",
        "engine": "duckdb",
    }
    events: list[str] = []
    rejected = check(**options, constraints={"not": {}}, _progress=events.append)
    assert rejected.divergence_status.value == "INCONCLUSIVE"
    assert events and set(events) == {"rejected"}

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("execution failed")

    monkeypatch.setattr(hosts, "_execute_duckdb", fail)
    events.clear()
    failed = check(**options, _progress=events.append)
    assert failed.divergence_status.value == "INCONCLUSIVE"
    assert events == ["error"]
