import sqlite3
from pathlib import Path

from isitright import check
from isitright.packs.sql.fixture_replay import replay_fixture as replay
from isitright.packs.sql.reports import write_case_report


def test_strict_generated_column_reproducer_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "strict.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE metric(
                id INTEGER PRIMARY KEY,
                base INTEGER NOT NULL,
                doubled INTEGER GENERATED ALWAYS AS (base * 2) STORED
            ) STRICT;
            INSERT INTO metric(id, base) VALUES (1, 3);
            """
        )

    result = check(
        database=database,
        reference_sql="SELECT doubled FROM metric",
        candidate_sql="SELECT base FROM metric",
    )
    write_case_report(result, tmp_path / "strict-artifacts")

    assert result.findings
    assert result.findings[0].minimization["rows_after"] == 1
    assert replay(
        tmp_path / "strict-artifacts" / "case_report.json",
        tmp_path / "strict-artifacts" / "counterexample.sql",
    )["reproduced"]


def test_without_rowid_composite_key_reproducer_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "without-rowid.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE item(
                group_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                label TEXT NOT NULL COLLATE NOCASE,
                PRIMARY KEY(group_id, item_id)
            ) WITHOUT ROWID;
            INSERT INTO item VALUES (1, 1, 'same'), (1, 2, 'same');
            """
        )

    result = check(
        database=database,
        reference_sql="SELECT label FROM item",
        candidate_sql="SELECT DISTINCT label FROM item",
    )
    write_case_report(result, tmp_path / "without-rowid-artifacts")

    assert result.findings
    assert result.findings[0].minimization["rows_after"] == 2
    assert replay(
        tmp_path / "without-rowid-artifacts" / "case_report.json",
        tmp_path / "without-rowid-artifacts" / "counterexample.sql",
    )["reproduced"]


def test_cyclic_deferred_foreign_keys_survive_reproduction(tmp_path: Path) -> None:
    database = tmp_path / "cycle.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE a(
                id INTEGER PRIMARY KEY,
                b_id INTEGER NOT NULL REFERENCES b(id) DEFERRABLE INITIALLY DEFERRED,
                label TEXT NOT NULL
            );
            CREATE TABLE b(
                id INTEGER PRIMARY KEY,
                a_id INTEGER NOT NULL REFERENCES a(id) DEFERRABLE INITIALLY DEFERRED
            );
            BEGIN;
            INSERT INTO a VALUES (1, 1, 'same'), (2, 2, 'same');
            INSERT INTO b VALUES (1, 1), (2, 2);
            COMMIT;
            """
        )

    result = check(
        database=database,
        reference_sql="SELECT label FROM a",
        candidate_sql="SELECT DISTINCT label FROM a",
    )
    write_case_report(result, tmp_path / "cycle-artifacts")

    assert result.findings
    assert result.findings[0].minimization["rows_after"] == 4
    assert replay(
        tmp_path / "cycle-artifacts" / "case_report.json",
        tmp_path / "cycle-artifacts" / "counterexample.sql",
    )["reproduced"]
