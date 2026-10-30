import importlib.util
import sqlite3

import pytest

from isitright.packs.sql.postgres_ddl import parse_postgres_database_schema
from isitright.packs.sql.postgres_server import _postgres_server
from isitright.packs.sql.sqlite_schema import introspect_schema
from isitright.packs.sql.state import DatabaseState, TableState
from isitright.packs.sql.state_loader import StateLoadError, load_state

DDL = (
    'CREATE TABLE "parent table" (id INTEGER PRIMARY KEY)',
    'CREATE TABLE child (parent_id INTEGER REFERENCES "parent table"(id), label TEXT)',
)
STATE = DatabaseState(
    (
        TableState("child", ("parent_id", "label"), ((1, "'); DROP TABLE child; --"), (1, "x"))),
        TableState("parent table", ("id",), ((1,), (2,))),
    )
)


def _schema():
    with sqlite3.connect(":memory:") as connection:
        for statement in DDL:
            connection.execute(statement)
        return introspect_schema(connection)


def _check_join(connection):
    inner = connection.execute(
        'SELECT p.id FROM "parent table" p JOIN child c ON p.id = c.parent_id'
    ).fetchall()
    outer = connection.execute(
        'SELECT p.id FROM "parent table" p LEFT JOIN child c ON p.id = c.parent_id'
    ).fetchall()
    assert sorted(inner) == [(1,), (1,)]
    assert sorted(outer) == [(1,), (1,), (2,)]
    assert connection.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 2


def test_load_related_state_into_sqlite_with_bound_values() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in DDL:
            connection.execute(statement)
        load_state(_schema(), STATE, execute=connection.execute, parameter="?")
        _check_join(connection)


@pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("embedded_postgres", "psycopg")),
    reason="optional PostgreSQL dependencies not installed",
)
def test_load_same_related_state_into_native_postgres() -> None:
    with (
        _postgres_server() as (psycopg, uri),
        psycopg.connect(uri, autocommit=True) as connection,
    ):
        for statement in DDL:
            connection.execute(statement)
        load_state(_schema(), STATE, execute=connection.execute, parameter="%s")
        _check_join(connection)
        ddl = (
            "CREATE TABLE customers (id INTEGER PRIMARY KEY);"
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, "
            "customer_id INTEGER REFERENCES customers(id))"
        )
        schema = parse_postgres_database_schema(ddl)
        for table in schema.tables:
            connection.execute(table.ddl)
        state = DatabaseState(
            (
                TableState("orders", ("id", "customer_id"), ((10, 1),)),
                TableState("customers", ("id",), ((1,), (2,))),
            )
        )
        load_state(schema, state, execute=connection.execute, parameter="%s")
        assert connection.execute(
            "SELECT customers.id FROM customers LEFT JOIN orders "
            "ON customers.id = orders.customer_id ORDER BY customers.id"
        ).fetchall() == [(1,), (2,)]


def test_load_rejects_bad_shape_before_inserting() -> None:
    schema = _schema()
    executed = []
    bad = DatabaseState((STATE.tables[1], TableState("child", ("label",), (("wrong",),))))
    with pytest.raises(StateLoadError, match="columns"):
        load_state(schema, bad, execute=lambda sql, values: executed.append(sql), parameter="?")
    assert not executed
    with pytest.raises(StateLoadError, match="unknown table"):
        load_state(
            schema,
            DatabaseState((TableState("unknown", ("id",), ((1,),)),)),
            execute=lambda sql, values: executed.append(sql),
            parameter="?",
        )
    assert not executed


def test_load_rejects_foreign_key_cycles_before_writing() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id))")
        connection.execute("CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id))")
        schema = introspect_schema(connection)
        state = DatabaseState(
            (TableState("a", ("id", "b_id"), ((1, 1),)), TableState("b", ("id", "a_id"), ((1, 1),)))
        )
        with pytest.raises(StateLoadError, match="cyclic"):
            load_state(schema, state, execute=connection.execute, parameter="?")
        assert connection.execute("SELECT COUNT(*) FROM a").fetchone()[0] == 0
