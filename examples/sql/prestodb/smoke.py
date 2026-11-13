# ruff: noqa: E402
# Proposed fixture: pending owner review (written by Claude; tested only against a fake connection).
"""Send the Presto fidelity fixtures, with their state inlined, to PrestoDB through your connection.

The Presto fixtures are confirmed on Trino (`examples/sql/trino/smoke.py`); Trino is not PrestoDB.
This runs the same fixtures through a function you supply, ``run(sql) -> (columns, rows)``, the same
contract as ``isitright sql check --confirm connection``, so it reaches an engine isitright cannot
(a PrestoDB behind your company's gateway). Your function is trusted code: it runs here, with your
credentials, and nothing else is sent. Each query is inline (no table is read): the host refuses
any text that still names a table before calling your function.

    python examples/sql/prestodb/smoke.py --connection my_module:run --trust-code \
        --engine-version 0.289 OUT.json [--observations tests/warehouse_native_observations.json]

The connection function raises an exception for a query error (the fixture's outcome is then
``ERROR``, which counts only if it carries the fixture's ``native_error`` name) and ``OSError``
(``ConnectionError``, ``TimeoutError``) when it cannot reach the engine, which stops the run instead
of being counted. With ``--observations`` the outcomes are merged into that file under the engine
name ``prestodb``, next to the Trino and BigQuery records, which the fidelity tests read.
See `connection_example.py` for a connection written for the `presto-python-client` package.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.inline import inline_sql
from isitright.packs.sql.mapping import build_model
from isitright.packs.sql.native import ConnectionHost, NativeHostError, load_connection
from isitright.packs.sql.replaying import _state
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables
from tests.warehouse_fixtures import ERROR, FIXTURES, PRESTO_DDL, PRESTO_ROWS

ENGINE = "prestodb"


def _norm(value: Any, ordered: bool) -> Any:
    return sorted(value, key=repr) if isinstance(value, list) and not ordered else value


def run_fixtures(host: ConnectionHost, fixtures: list[Any] | None = None) -> list[dict[str, Any]]:
    """Each Presto fixture's outcome on the host. A ``NativeHostError`` (the engine could not be
    reached) propagates: it is not an outcome."""
    dialect = get_dialect("presto")
    db = parse_warehouse_schema(PRESTO_DDL, dialect)
    state = _state(build_model(db, "presto"), PRESTO_ROWS)
    rows = []
    for fixture in fixtures if fixtures is not None else FIXTURES:
        if fixture.dialect != "presto" or fixture.status == "detected":
            continue
        text = inline_sql(
            resolve_tables(parse_query(fixture.query, dialect), db), dialect, db, state
        )
        try:
            result = host.run_inline(text, dialect, timeout_seconds=60, max_rows=100)
            observed: Any = [[cell.value for cell in row] for row in result.rows]
            detail = ""
        except QueryExecutionError as error:
            observed, detail = ERROR, str(error)[:300]
        expected = fixture.extra.get(f"native_{ENGINE}", fixture.native)
        if expected is None:
            outcome = "no recorded outcome"
        elif _norm(observed, fixture.ordered) == _norm(expected, fixture.ordered):
            outcome = "confirmed"
            if observed == ERROR and fixture.native_error and fixture.native_error not in detail:
                outcome = "DIFFERS (another error)"
        else:
            outcome = "DIFFERS"
        rows.append(
            {
                "id": fixture.id,
                "status": fixture.status,
                "outcome": outcome,
                "expected_native": expected,
                "observed_native": observed,
                "emulated": fixture.emulated,
                "observed_equals_emulated": _norm(observed, fixture.ordered)
                == _norm(fixture.emulated, fixture.ordered),
                "detail": detail,
            }
        )
    return rows


def merge_observations(path: Path, rows: list[dict[str, Any]], version: str, date: str) -> None:
    """Add or replace this engine's records; other engines' records for the same fixture stay."""
    book = json.loads(path.read_text(encoding="utf-8"))
    kept = {(r["id"], r["engine"]): r for r in book["records"]}
    for row in rows:
        kept[(row["id"], ENGINE)] = {
            "id": row["id"],
            "engine": ENGINE,
            "engine_version": version,
            "date": date,
            "observed": row["observed_native"],
            "error": row["detail"] if row["observed_native"] == ERROR else "",
        }
    book["records"] = list(kept.values())
    path.write_text(json.dumps(book, indent=1) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python examples/sql/prestodb/smoke.py")
    parser.add_argument("out", type=Path)
    parser.add_argument("--connection", required=True, help="module:function, run(sql)")
    parser.add_argument("--trust-code", action="store_true", help="the function runs here")
    parser.add_argument("--engine-version", required=True, help="the PrestoDB server's version")
    parser.add_argument("--observations", type=Path, help="merge into this observations file")
    args = parser.parse_args(argv)
    if not args.trust_code:
        print("refusing to load --connection without --trust-code: it runs here", file=sys.stderr)
        return 2
    host = ConnectionHost(run=load_connection(args.connection))
    try:
        rows = run_fixtures(host)
    except NativeHostError as error:
        print(f"stopped: the engine could not be reached: {error}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    today = datetime.date.today().isoformat()
    args.out.write_text(
        json.dumps(
            {
                "engine": ENGINE,
                "engine_version": args.engine_version,
                "date": today,
                "counts": counts,
                "fixtures": rows,
            },
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    if args.observations:
        merge_observations(args.observations, rows, args.engine_version, today)
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
