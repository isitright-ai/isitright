import sqlite3

import pytest

from isitright.packs.sql import sqlite_schema
from isitright.packs.sql.errors import SqlInputError as PostgresInputError
from isitright.packs.sql.postgres_ddl import parse_postgres_database_schema, parse_schema
from isitright.packs.sql.schema import DatabaseSchema


def test_sqlite_multitable_schema_uses_shared_representation() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(
            """
            CREATE TABLE parent (id INTEGER PRIMARY KEY, label TEXT UNIQUE);
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER REFERENCES parent(id),
                value TEXT
            );
            """
        )
        schema = sqlite_schema.introspect_schema(connection)

    assert isinstance(schema, DatabaseSchema)
    assert sqlite_schema.DatabaseSchema is DatabaseSchema
    assert [table.name for table in schema.tables] == ["child", "parent"]
    foreign_key = schema.table("child").foreign_keys[0]
    assert (foreign_key.from_column, foreign_key.referenced_table, foreign_key.to_column) == (
        "parent_id",
        "parent",
        "id",
    )
    assert schema.table("parent").columns[1].declared_type == "TEXT"
    assert ("label",) in schema.table("parent").unique_columns
    with pytest.raises(KeyError):
        schema.table("missing")


def test_postgres_parser_produces_shared_schema_without_losing_native_ddl() -> None:
    parsed = parse_schema(
        "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER NOT NULL, note TEXT)"
    )
    schema = parsed.database
    assert isinstance(schema, DatabaseSchema)
    table = schema.table("item")
    assert table.ddl == parsed.ddl
    assert "CREATE TABLE" in table.ddl
    columns = [(c.name, c.declared_type, c.not_null, c.primary_key_position) for c in table.columns]
    assert columns == [
        ("id", "INTEGER", True, 1),
        ("amount", "INTEGER", True, 0),
        ("note", "TEXT", False, 0),
    ]


def test_postgres_multitable_schema_has_resolved_foreign_key() -> None:
    schema = parse_postgres_database_schema(
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));"
        "CREATE TABLE parent (id INTEGER PRIMARY KEY, label TEXT);"
    )
    assert [table.name for table in schema.tables] == ["child", "parent"]
    key = schema.table("child").foreign_keys[0]
    assert (key.from_column, key.referenced_table, key.to_column) == ("parent_id", "parent", "id")
    assert schema.table("parent").columns[0].not_null
    with pytest.raises(PostgresInputError):
        parse_schema(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
        )


@pytest.mark.parametrize(
    "ddl",
    [
        "",
        "CREATE TABLE a (id INTEGER PRIMARY KEY); CREATE TABLE a (id INTEGER PRIMARY KEY)",
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b INTEGER REFERENCES absent(id))",
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b INTEGER REFERENCES b(value));"
        "CREATE TABLE b (id INTEGER PRIMARY KEY, value INTEGER)",
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b INTEGER REFERENCES b(id) ON DELETE CASCADE);"
        "CREATE TABLE b (id INTEGER PRIMARY KEY)",
        "CREATE TABLE a (id INTEGER PRIMARY KEY); DROP TABLE a",
        "CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id));"
        "CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id))",
    ],
)
def test_postgres_multitable_schema_rejects_unsupported_or_unsafe_input(ddl: str) -> None:
    with pytest.raises(PostgresInputError):
        parse_postgres_database_schema(ddl)
