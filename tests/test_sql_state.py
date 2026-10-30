import hashlib
import sqlite3
from pathlib import Path

import pytest

from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from isitright.packs.sql.mapping import build_model, generate_base_state
from isitright.packs.sql.postgres_ddl import _render_state, parse_query, parse_schema
from isitright.packs.sql.sqlite_sandbox import SQLiteSandbox
from isitright.packs.sql.sqlite_state import snapshot_sqlite
from isitright.packs.sql.state import DatabaseState, TableState


def test_multitable_state_preserves_relationships_and_duplicate_rows() -> None:
    state = DatabaseState(
        (
            TableState("customer", ("id",), ((1,), (2,))),
            TableState("orders", ("customer_id", "value"), ((1, None), (1, None))),
        )
    )
    assert state.records() == {
        "customer": [{"id": 1}, {"id": 2}],
        "orders": [{"customer_id": 1, "value": None}, {"customer_id": 1, "value": None}],
    }


def test_state_rejects_ambiguous_shapes() -> None:
    with pytest.raises(ValueError, match="column"):
        TableState("t", ("id", "id"), ())
    with pytest.raises(ValueError, match="width"):
        TableState("t", ("id",), ((1, 2),))
    with pytest.raises(ValueError, match="table"):
        DatabaseState((TableState("t", (), ()), TableState("t", (), ())))


def test_sqlite_snapshot_reads_disposable_copy_without_modifying_source(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE "parent table" (id INTEGER PRIMARY KEY);
            CREATE TABLE child (parent_id INTEGER REFERENCES "parent table"(id), value TEXT);
            INSERT INTO "parent table" VALUES (1);
            INSERT INTO child VALUES (1, 'same'), (1, 'same');
            """
        )
    before = hashlib.sha256(path.read_bytes()).digest()
    with SQLiteSandbox(path) as sandbox:
        assert sandbox.connection is not None
        assert sandbox.schema is not None
        state = snapshot_sqlite(sandbox.connection, sandbox.schema)
    assert state.records() == {
        "child": [{"parent_id": 1, "value": "same"}, {"parent_id": 1, "value": "same"}],
        "parent table": [{"id": 1}],
    }
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_postgres_candidates_are_data_states_and_rendering_rejects_untrusted_values() -> None:
    schema = parse_schema("CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER)")
    query = parse_query("SELECT id FROM item WHERE amount > 5", schema)
    assert query is not None
    base = generate_base_state(build_model(schema.database, "postgres"), [])
    assert isinstance(base, DatabaseState)
    assert 'INSERT INTO "item"' in _render_state(schema, base)
    for state in (
        DatabaseState((TableState("wrong", ("id", "amount"), ((1, 5),)),)),
        DatabaseState((TableState("item", ("amount", "id"), ((5, 1),)),)),
        DatabaseState((TableState("item", ("id", "amount"), ((1, "0); DROP TABLE item"),)),)),
        DatabaseState((TableState("item", ("id", "amount"), ((1, True),)),)),
    ):
        with pytest.raises(PostgresInputError):
            _render_state(schema, state)
