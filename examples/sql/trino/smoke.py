# ruff: noqa: E402
# Proposed fixture: pending owner review (runs the Presto fidelity fixtures on a local Trino).
"""Send the Presto fidelity fixtures, with their state inlined, to a Trino server and compare with
the fixtures' recorded outcomes.

Usage (a Trino server on localhost:8080, for example `docker run -d -p 127.0.0.1:8080:8080
trinodb/trino`, and `uv pip install "trino>=0.330,<1"`):

    python examples/sql/trino/smoke.py OUT.json [tests/warehouse_native_observations.json]

With the second argument, the observations (outcome, error, Trino version, date) are merged into
that file, which the fidelity tests read. Only a query error counts as the expected ERROR, and
only when it carries the fixture's ``native_error`` name; a connection failure or any other
exception stops the run.
"""

import datetime
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from isitright.packs.sql import TrinoHost
from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.inline import inline_sql
from isitright.packs.sql.mapping import build_model
from isitright.packs.sql.replaying import _state
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables
from tests.warehouse_fixtures import ERROR, FIXTURES, PRESTO_DDL, PRESTO_ROWS

dialect = get_dialect("trino")
db = parse_warehouse_schema(PRESTO_DDL, dialect)
state = _state(build_model(db, "trino"), PRESTO_ROWS)
host = TrinoHost(catalog="memory", schema="default")
rows = []
for f in FIXTURES:
    if f.dialect != "presto" or f.status == "detected":
        continue
    tree = resolve_tables(parse_query(f.query, dialect), db)
    text = inline_sql(tree, dialect, db, state)
    try:
        res = host.run_inline(text, dialect, timeout_seconds=60, max_rows=100)
        observed = [[c.value for c in r] for r in res.rows]
        detail = ""
    except QueryExecutionError as e:
        observed, detail = ERROR, str(e)[:300]

    def norm(v, ordered=f.ordered):
        return sorted(v, key=repr) if isinstance(v, list) and not ordered else v

    if f.native is None:
        outcome = "no documented outcome"
    elif norm(observed) == norm(f.native):
        outcome = "confirmed"
        if observed == ERROR and f.native_error and f.native_error not in detail:
            outcome = "DIFFERS (another error)"
    else:
        outcome = "DIFFERS"
    rows.append(
        {
            "id": f.id,
            "status": f.status,
            "outcome": outcome,
            "expected_native": f.native,
            "observed_native": observed,
            "emulated": f.emulated,
            "observed_equals_emulated": norm(observed) == norm(f.emulated),
            "detail": detail,
        }
    )
counts = {}
for r in rows:
    counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
with urllib.request.urlopen("http://127.0.0.1:8080/v1/info", timeout=10) as info:
    version = str(json.load(info)["nodeVersion"]["version"])
today = datetime.date.today().isoformat()
out = {
    "fixtures": rows,
    "counts": counts,
    "trino_version": version,
    "date": today,
}
Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
if len(sys.argv) > 2:
    target = Path(sys.argv[2])
    book = json.loads(target.read_text(encoding="utf-8"))
    kept = {(r["id"], r["engine"]): r for r in book["records"]}  # other engines stay
    for r in rows:
        kept[(r["id"], "trino")] = {
            "id": r["id"],
            "engine": "trino",
            "engine_version": version,
            "date": today,
            "observed": r["observed_native"],
            "error": r["detail"] if r["observed_native"] == ERROR else "",
        }
    book["records"] = list(kept.values())
    target.write_text(json.dumps(book, indent=1) + "\n", encoding="utf-8", newline="\n")
print(counts)
for r in rows:
    print(
        r["id"],
        r["status"],
        r["outcome"],
        "eq-emulated" if r["observed_equals_emulated"] else "NE-emulated",
    )
    if r["outcome"] != "confirmed":
        print(
            "   exp",
            r["expected_native"],
            "obs",
            r["observed_native"],
            "emu",
            r["emulated"],
            r["detail"][:200],
        )
