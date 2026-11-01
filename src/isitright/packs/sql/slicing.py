"""A small SQLite database cut from a large one, for auditing a query pair on a few rows.

The SQL pack takes the whole database as the base world, and every proposal works on a copy of it,
so a database with many rows makes a case slow. A slice keeps the DDL and only the rows the
reference query used: the rows (by ``rowid``) that join and satisfy its ``WHERE``, up to ``cap``
joined tuples, plus up to ``pad`` rows of every other table the query names (subqueries), closed
under foreign keys so no kept row loses its parent.

An audit of a slice says "on worlds near this slice". The base world is chosen here, not the
original database, and a difference the two queries show on the slice itself is a base mismatch,
not a search result.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

DEFAULT_CAP = 25
DEFAULT_PAD = 5
_CLOSURE_ROUNDS = 6
_CHUNK = 500


class SliceError(ValueError):
    """The query cannot be sliced (a set operation, a CTE, no FROM, or a failing query)."""


@dataclass(frozen=True)
class SliceResult:
    path: Path
    rows: int
    tuples: int
    """Joined tuples of the reference query that were kept."""


def slice_database(
    source: str | PathLike[str],
    reference_sql: str,
    output: str | PathLike[str],
    *,
    cap: int = DEFAULT_CAP,
    pad: int = DEFAULT_PAD,
) -> SliceResult:
    """Write ``output``, a new SQLite file, with the rows ``reference_sql`` used in ``source``."""
    if cap < 1 or pad < 0:
        raise SliceError("cap must be at least 1 and pad at least 0")
    out = Path(output)
    if out.exists():
        raise SliceError(f"output already exists: {out}")
    try:
        tree = sqlglot.parse_one(reference_sql, read="sqlite")
    except ParseError as error:
        raise SliceError(f"SQL could not be parsed: {error}") from error
    if not isinstance(tree, exp.Select) or tree.args.get("with"):
        raise SliceError(f"only a plain SELECT can be sliced, not {type(tree).__name__}")
    from_ = tree.args.get("from_") or tree.args.get("from")
    joined = list(from_.find_all(exp.Table)) if from_ else []
    for join in tree.args.get("joins") or []:
        joined.extend(join.find_all(exp.Table))
    aliases = {t.alias_or_name: t.name for t in joined}
    if not aliases:
        raise SliceError("the query has no FROM clause")

    # Select each joined table's rowid; drop everything that reshapes or limits the result.
    probe = tree.copy()
    for key in ("group", "having", "order", "limit", "offset"):
        probe.set(key, None)
    probe.set("distinct", None)
    probe.set(
        "expressions",
        [exp.alias_(exp.column("rowid", table=a), f"_r{i}") for i, a in enumerate(aliases)],
    )
    try:
        connection = sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise SliceError(f"could not open the database: {error}") from error
    try:
        try:
            tuples = connection.execute(f"{probe.sql(dialect='sqlite')} LIMIT {cap}").fetchall()
        except sqlite3.Error as error:
            raise SliceError(f"the query could not be run for slicing: {error}") from error
        keep: dict[str, set[int]] = {}
        for i, table in enumerate(aliases.values()):
            keep.setdefault(table, set()).update(r[i] for r in tuples if r[i] is not None)
        for table in {t.name for t in tree.find_all(exp.Table)} - set(aliases.values()):
            keep.setdefault(table, set()).update(
                r[0] for r in connection.execute(f"SELECT rowid FROM {_q(table)} LIMIT {pad}")
            )
        _close_under_foreign_keys(connection, keep)
        rows = _write(connection, keep, out)
    except sqlite3.Error as error:
        raise SliceError(f"slicing failed: {error}") from error
    finally:
        connection.close()
    return SliceResult(out, rows, len(tuples))


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _close_under_foreign_keys(connection: sqlite3.Connection, keep: dict[str, set[int]]) -> None:
    """Add the parent rows the kept rows reference, until nothing is added."""
    foreign: dict[str, list[tuple[str, str, str | None]]] = {}
    for (table,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ):
        foreign[table] = [
            (r[2], r[3], r[4]) for r in connection.execute(f"PRAGMA foreign_key_list({_q(table)})")
        ]
    for _ in range(_CLOSURE_ROUNDS):
        grew = False
        for table, ids in list(keep.items()):
            for parent, child_column, parent_column in foreign.get(table, []):
                if not ids:
                    continue
                if parent_column is None:  # the parent's primary key
                    parent_column = next(
                        r[1]
                        for r in connection.execute(f"PRAGMA table_info({_q(parent)})")
                        if r[5] == 1
                    )
                marks = ",".join("?" * len(ids))
                found = connection.execute(
                    f"SELECT p.rowid FROM {_q(parent)} p WHERE p.{_q(parent_column)} IN "
                    f"(SELECT {_q(child_column)} FROM {_q(table)} WHERE rowid IN ({marks}))",
                    sorted(ids),
                ).fetchall()
                new = {r[0] for r in found} - keep.setdefault(parent, set())
                if new:
                    keep[parent] |= new
                    grew = True
        if not grew:
            return


def _write(connection: sqlite3.Connection, keep: dict[str, set[int]], out: Path) -> int:
    target = sqlite3.connect(out)
    try:
        for (sql,) in connection.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table', 'index') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ):
            target.execute(sql)
        target.execute("PRAGMA foreign_keys = OFF")
        total = 0
        for table, ids in keep.items():
            columns = [r[1] for r in connection.execute(f"PRAGMA table_info({_q(table)})")]
            names = ",".join(_q(c) for c in columns)
            ordered = sorted(ids)
            for start in range(0, len(ordered), _CHUNK):
                chunk = ordered[start : start + _CHUNK]
                marks = ",".join("?" * len(chunk))
                data = connection.execute(
                    f"SELECT {names} FROM {_q(table)} WHERE rowid IN ({marks})", chunk
                ).fetchall()
                target.executemany(
                    f"INSERT OR IGNORE INTO {_q(table)} VALUES ({','.join('?' * len(columns))})",
                    data,
                )
                total += len(data)
        target.commit()
        return total
    except sqlite3.Error:
        target.close()
        out.unlink(missing_ok=True)
        raise
    finally:
        target.close()
