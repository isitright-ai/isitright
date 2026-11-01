"""A slice keeps the rows the reference query used, closed under foreign keys."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from isitright.packs.sql.slicing import SliceError, slice_database


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "big.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE region (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE shop (id INTEGER PRIMARY KEY, region_id INTEGER REFERENCES region(id));
            CREATE TABLE sale (id INTEGER PRIMARY KEY, shop_id INTEGER REFERENCES shop(id), n INT);
            """
        )
        connection.executemany(
            "INSERT INTO region VALUES (?, ?)", [(i, f"r{i}") for i in range(10)]
        )
        connection.executemany("INSERT INTO shop VALUES (?, ?)", [(i, i % 10) for i in range(100)])
        connection.executemany(
            "INSERT INTO sale VALUES (?, ?, ?)", [(i, i % 100, i) for i in range(1000)]
        )
    return path


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_a_slice_keeps_the_used_rows_and_their_parents(database: Path, tmp_path: Path) -> None:
    out = tmp_path / "slice.sqlite"
    result = slice_database(database, "SELECT COUNT(*) FROM sale WHERE n >= 500", out, cap=10)
    assert result.tuples == 10 and _count(out, "sale") == 10
    assert _count(out, "shop") <= 10 and _count(out, "region") <= 10
    with sqlite3.connect(out) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_query_that_cannot_be_sliced_says_why(database: Path, tmp_path: Path) -> None:
    for sql in ("SELECT 1 UNION SELECT 2", "SELECT 1", "WITH c AS (SELECT 1) SELECT * FROM c"):
        with pytest.raises(SliceError):
            slice_database(database, sql, tmp_path / "x.sqlite")


def test_a_slice_never_overwrites_a_file(database: Path, tmp_path: Path) -> None:
    out = tmp_path / "exists.sqlite"
    out.write_text("keep", encoding="utf-8")
    with pytest.raises(SliceError, match="already exists"):
        slice_database(database, "SELECT * FROM sale", out)
    assert out.read_text(encoding="utf-8") == "keep"
