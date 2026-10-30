import json
import sqlite3
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from isitright import CheckConfig, check, check_suite
from isitright.cli import EXIT_POLICY_TRIGGERED, app
from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import audit as audit_module
from isitright.packs.sql.fixture_replay import main as replay_main
from isitright.packs.sql.fixture_replay import replay_fixture
from isitright.packs.sql.reports import write_case_report, write_suite_report
from isitright.packs.sql.reproducer import sqlite_reproducer
from isitright.packs.sql.sqlite_sandbox import QueryResourceLimitError
from isitright.packs.sql.sqlite_schema import introspect_schema
from isitright.packs.sql.state import DatabaseState, TableState


def _background_database(path: Path, *, rows: int = 200) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE noise(id INTEGER PRIMARY KEY, note TEXT NOT NULL);
            INSERT INTO noise VALUES (1, 'not referenced');
            CREATE TABLE values_table(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        connection.executemany(
            "INSERT INTO values_table(id, value) VALUES (?, ?)",
            [(index, "duplicate") for index in range(1, rows + 1)],
        )
    return path


def test_minimization_shrinks_background_rows_and_replay_reproduces(tmp_path: Path) -> None:
    database = _background_database(tmp_path / "source.sqlite")
    result = check(
        database=database,
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )

    (finding,) = result.findings
    assert finding.minimization["complete"] is True
    assert finding.minimization["rows_before"] == 200
    assert finding.minimization["rows_after"] == 2
    assert set(finding.divergence["candidate_state"]) == {"values_table"}

    written = write_case_report(result, tmp_path / "artifacts")
    reproducer = tmp_path / "artifacts" / "counterexample.sql"
    assert reproducer in written
    script = reproducer.read_text(encoding="utf-8")
    assert "CREATE TABLE noise" not in script
    assert "SELECT DISTINCT" not in script
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(script)
        reference = connection.execute("SELECT value FROM values_table").fetchall()
        candidate = connection.execute("SELECT DISTINCT value FROM values_table").fetchall()
    assert reference == [("duplicate",), ("duplicate",)]
    assert candidate == [("duplicate",)]
    replay_result = replay_fixture(tmp_path / "artifacts" / "case_report.json", reproducer)
    assert replay_result["reproduced"] is True


def test_minimization_budget_returns_best_known_counterexample(tmp_path: Path) -> None:
    result = check(
        database=_background_database(tmp_path / "source.sqlite"),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
        config=CheckConfig(minimization_max_attempts=1),
    )

    (finding,) = result.findings
    assert finding.minimization["complete"] is False
    assert 2 <= finding.minimization["rows_after"] < 200


def test_reproducer_preserves_standalone_unique_indexes() -> None:
    with sqlite3.connect(":memory:") as source:
        source.executescript(
            """
            CREATE TABLE item(id INTEGER PRIMARY KEY, code TEXT NOT NULL);
            CREATE UNIQUE INDEX item_code_unique ON item(code);
            INSERT INTO item VALUES (1, 'A');
            """
        )
        schema = introspect_schema(source)
    script = sqlite_reproducer(
        schema, DatabaseState((TableState("item", ("id", "code"), ((1, "A"),)),))
    )

    with sqlite3.connect(":memory:") as replay_database:
        replay_database.executescript(script)
        with pytest.raises(sqlite3.IntegrityError):
            replay_database.execute("INSERT INTO item VALUES (2, 'A')")


def test_reproducer_is_deterministic(tmp_path: Path) -> None:
    database = _background_database(tmp_path / "source.sqlite", rows=8)
    arguments = {
        "database": database,
        "reference_sql": "SELECT value FROM values_table",
        "candidate_sql": "SELECT DISTINCT value FROM values_table",
    }

    first = check(**arguments)
    second = check(**arguments)

    assert (
        first.findings[0].divergence["reproducer_sql"]
        == (second.findings[0].divergence["reproducer_sql"])
    )


def test_replay_command_prints_verified_outputs(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    result = check(
        database=_background_database(tmp_path / "source.sqlite", rows=3),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )
    write_case_report(result, tmp_path / "artifacts")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "isitright.replay",
            "--report",
            str(tmp_path / "artifacts" / "case_report.json"),
            "--fixture",
            str(tmp_path / "artifacts" / "counterexample.sql"),
        ],
    )

    replay_main()

    assert '"reproduced": true' in capsys.readouterr().out


def test_replay_command_reports_invalid_input(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "isitright.replay",
            "--report",
            str(tmp_path / "missing.json"),
            "--fixture",
            str(tmp_path / "missing.sql"),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        replay_main()

    assert raised.value.code == 1
    assert "replay error" in capsys.readouterr().err


def test_replay_rejects_fixture_attachment(tmp_path: Path) -> None:
    result = check(
        database=_background_database(tmp_path / "source.sqlite", rows=2),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )
    write_case_report(result, tmp_path / "artifacts")
    malicious_fixture = tmp_path / "malicious.sql"
    attached_database = tmp_path / "attached.sqlite"
    malicious_fixture.write_text(
        f"ATTACH DATABASE '{attached_database.as_posix()}' AS external;",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        replay_fixture(tmp_path / "artifacts" / "case_report.json", malicious_fixture)

    assert not attached_database.exists()


def test_json_replay_rejects_a_tampered_schema(tmp_path: Path) -> None:
    from isitright.core.replay import load_artifact
    from isitright.packs.sql import replay_artifact

    result = check(
        database=_background_database(tmp_path / "source.sqlite", rows=2),
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )
    write_case_report(result, tmp_path / "artifacts")
    artifact = load_artifact(tmp_path / "artifacts" / "replay.json")
    attached = tmp_path / "attached.sqlite"
    artifact.host["schema_ddl"] = [f"ATTACH DATABASE '{attached.as_posix()}' AS external"]

    with pytest.raises(Exception, match=r"not authorized|invalid recorded schema"):
        replay_artifact(artifact)
    assert not attached.exists()


def test_replay_applies_result_row_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _background_database(tmp_path / "source.sqlite")
    result = check(
        database=database,
        reference_sql="SELECT value FROM values_table",
        candidate_sql="SELECT DISTINCT value FROM values_table",
    )
    write_case_report(result, tmp_path / "artifacts")
    monkeypatch.setattr("isitright.packs.sql.fixture_replay._REPLAY_MAX_RESULT_ROWS", 1)

    with pytest.raises(QueryResourceLimitError, match="1-row limit"):
        replay_fixture(
            tmp_path / "artifacts" / "case_report.json",
            tmp_path / "artifacts" / "counterexample.sql",
        )


def test_suite_isolates_cases_ranks_results_and_preserves_metadata(tmp_path: Path) -> None:
    database = _background_database(tmp_path / "source.sqlite", rows=4)
    cases = tmp_path / "cases.jsonl"
    records = [
        {
            "case_id": "agreement",
            "reference_sql": "SELECT value FROM values_table",
            "candidate_sql": "SELECT value FROM values_table",
        },
        {
            "case_id": "error",
            "reference_sql": "SELECT missing FROM absent_table",
            "candidate_sql": "SELECT 1",
        },
        {
            "case_id": "finding",
            "reference_sql": "SELECT value FROM values_table",
            "candidate_sql": "SELECT DISTINCT value FROM values_table",
            "agent": "fixture-agent",
        },
    ]
    cases.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    result = check_suite(
        database=database,
        cases=cases,
        config=CheckConfig(max_attempts=2),
    )

    assert [case.case_id for case in result.cases] == ["finding", "error", "agreement"]
    assert result.cases[0].inputs["question"] is None
    assert result.cases[1].divergence_status is DivergenceStatus.INCONCLUSIVE
    assert result.totals.cases == 3
    assert result.totals.by_divergence_status["COUNTEREXAMPLE_FOUND"] == 1
    # The only finding is on the original data, so no mutation family is credited.
    assert result.totals.by_family == {}

    written = write_suite_report(result, tmp_path / "suite-artifacts")
    assert tmp_path / "suite-artifacts" / "suite_report.json" in written
    assert tmp_path / "suite-artifacts" / "suite_report.md" in written
    assert any(path.name == "counterexample.sql" for path in written)


def test_cli_fail_on_any_counterexample_uses_policy_exit_code(tmp_path: Path) -> None:
    database = _background_database(tmp_path / "source.sqlite", rows=3)
    reference = tmp_path / "reference.sql"
    candidate = tmp_path / "candidate.sql"
    reference.write_text("SELECT value FROM values_table", encoding="utf-8")
    candidate.write_text("SELECT DISTINCT value FROM values_table", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "sql",
            "check",
            "--database",
            str(database),
            "--reference",
            str(reference),
            "--candidate",
            str(candidate),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--fail-on",
            "any-counterexample",
        ],
    )

    assert result.exit_code == EXIT_POLICY_TRIGGERED
    assert (tmp_path / "artifacts" / "counterexample.sql").is_file()


def test_suite_contains_an_unexpected_case_error(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    database = _background_database(tmp_path / "source.sqlite", rows=2)
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"case_id":"broken","reference_sql":"SELECT 1","candidate_sql":"SELECT 1"}\n',
        encoding="utf-8",
    )

    def raise_unexpected(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("isolated fixture error")

    monkeypatch.setattr(audit_module.SqlAudit, "check", raise_unexpected)
    result = check_suite(database=database, cases=cases)

    assert result.totals.cases == 1
    assert result.cases[0].divergence_status is DivergenceStatus.INCONCLUSIVE
    assert result.cases[0].errors[0]["code"] == "CASE_INTERNAL_ERROR"
