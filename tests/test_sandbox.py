import hashlib
import sqlite3
from pathlib import Path

import pytest

from isitright.packs.sql.models import CanonicalValueKind
from isitright.packs.sql.sqlite_sandbox import (
    DatabaseInputError,
    QueryExecutionError,
    QueryResourceLimitError,
    QueryTimeoutError,
    SQLiteSandbox,
    execute_query,
)


def _database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE parent(id INTEGER PRIMARY KEY, label TEXT NOT NULL);
            CREATE TABLE child(
                id INTEGER PRIMARY KEY,
                parent_id INTEGER REFERENCES parent(id),
                payload BLOB
            );
            INSERT INTO parent VALUES (1, 'one');
            INSERT INTO child VALUES (1, 1, X'00FF');
            """
        )
    return path


def test_sandbox_introspects_and_canonicalizes_storage_classes(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    with SQLiteSandbox(database) as sandbox:
        parent = sandbox.schema.table("parent") if sandbox.schema else None
        result = sandbox.execute(
            "SELECT NULL, 1, 1.5, label, payload FROM parent JOIN child",
            timeout_seconds=1,
        )

    assert parent is not None
    assert [column.name for column in parent.columns] == ["id", "label"]
    assert result.rows[0][0].kind is CanonicalValueKind.NULL
    assert result.rows[0][1].kind is CanonicalValueKind.INTEGER
    assert result.rows[0][2].kind is CanonicalValueKind.FLOAT
    assert result.rows[0][3].kind is CanonicalValueKind.TEXT
    assert result.rows[0][4].kind is CanonicalValueKind.BINARY
    assert result.rows[0][4].value == "AP8="


def test_query_only_blocks_writes_to_disposable_copy_and_source(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    with (
        SQLiteSandbox(database) as sandbox,
        pytest.raises(QueryExecutionError, match=r"readonly|not authorized"),
    ):
        sandbox.execute("DELETE FROM parent", timeout_seconds=1)

    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent").fetchone() == (1,)


def test_authorizer_blocks_writes_even_without_query_only() -> None:
    """The authorizer is a second barrier: it holds on a plain writable connection too."""
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        with pytest.raises(QueryExecutionError, match="not authorized"):
            execute_query(connection, "DELETE FROM parent", timeout_seconds=1)


def test_authorizer_blocks_extension_loading(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    with (
        SQLiteSandbox(database) as sandbox,
        pytest.raises(QueryExecutionError, match="not authorized"),
    ):
        sandbox.execute("SELECT load_extension('untrusted')", timeout_seconds=1)


def test_result_row_limit_stops_materialization(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    with (
        SQLiteSandbox(database) as sandbox,
        pytest.raises(QueryResourceLimitError, match="2-row limit"),
    ):
        sandbox.execute(
            "SELECT value FROM (SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3)",
            timeout_seconds=1,
            max_result_rows=2,
        )


def test_progress_handler_interrupts_runaway_query(tmp_path: Path) -> None:
    database = _database(tmp_path / "db.sqlite")
    sql = """
        WITH RECURSIVE forever(value) AS (
            SELECT 1 UNION ALL SELECT value + 1 FROM forever
        )
        SELECT SUM(value) FROM forever
    """
    with SQLiteSandbox(database) as sandbox, pytest.raises(QueryTimeoutError):
        sandbox.execute(sql, timeout_seconds=0.001)


def test_sandbox_requires_context_and_existing_file(tmp_path: Path) -> None:
    sandbox = SQLiteSandbox(tmp_path / "missing.sqlite")
    with pytest.raises(RuntimeError, match="must be entered"):
        sandbox.execute("SELECT 1", timeout_seconds=1)
    with pytest.raises(DatabaseInputError, match="not readable"):
        sandbox.__enter__()


def test_sandbox_rejects_foreign_key_violations(tmp_path: Path) -> None:
    database = tmp_path / "invalid.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            CREATE TABLE child(parent_id INTEGER REFERENCES parent(id));
            INSERT INTO child VALUES (999);
            """
        )
    with pytest.raises(DatabaseInputError, match="foreign-key"):
        SQLiteSandbox(database).__enter__()
