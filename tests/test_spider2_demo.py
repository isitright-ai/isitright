# Proposed fixture: pending owner review (the equivalence fixture below is constructed by Claude).
"""The Spider 2.0-lite demo data: the selection, the wildcard rewrite, and its equivalence on
DuckDB with tiny shard tables. The BigQuery equivalence test is an owner step (the runbook)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables, to_duckdb

DEMO = Path(__file__).resolve().parents[1] / "examples" / "sql" / "spider2"
BQ = get_dialect("bigquery")
TASKS = [json.loads(line) for line in (DEMO / "tasks.jsonl").read_text("utf-8").splitlines()]
REWRITTEN = [t for t in TASKS if t["rewrites"]]


def test_the_selection_is_the_rule_applied_to_the_pinned_commits() -> None:
    selection = json.loads((DEMO / "selection.json").read_text("utf-8"))
    assert selection["counts"] == {
        "correct_in_schemagate_run": 94,
        "bigquery_tasks_with_published_gold": 148,
        "selected": 73,
    }
    assert selection["task_ids"] == sorted(selection["task_ids"])
    assert [t["id"] for t in TASKS] == selection["task_ids"]
    assert len(selection["spider2_commit"]) == 40 and len(selection["schemagate_commit"]) == 40
    for name in ("Spider2-MIT.txt", "schemagate-Apache-2.0.txt"):
        assert (DEMO / "licenses" / name).stat().st_size > 500


@pytest.mark.parametrize("task", REWRITTEN, ids=lambda t: t["id"])
def test_a_rewritten_query_parses_and_reads_only_declared_tables(task: dict) -> None:
    ddl = (DEMO / "ddl" / f"{task['id']}.sql").read_text("utf-8")
    try:
        schema = parse_warehouse_schema(ddl, BQ)
    except SqlInputError as error:
        assert "GEOGRAPHY" in str(error)  # reported UNSUPPORTED by the audit, not a rewrite fault
        return
    names = {t.name for t in schema.tables}
    for side in ("gold", "candidate"):
        original = (DEMO / "original" / side / f"{task['id']}.sql").read_text("utf-8")
        rewritten = (DEMO / side / f"{task['id']}.sql").read_text("utf-8")
        assert not re.search(r"`[^`]*\*`", rewritten)
        if "*`" not in original:  # this side reads no wildcard table: nothing was rewritten
            assert rewritten == original
        tree = sqlglot.parse_one(rewritten, read="bigquery")
        physical = {
            s.name
            for scope in traverse_scope(tree)
            for s in scope.sources.values()
            if isinstance(s, exp.Table)
        }
        assert physical <= names, physical - names
        assert not any("*" in name for name in physical)
        # the resolved, translated query is what the audit runs
        try:
            db_tree = resolve_tables(parse_query(rewritten, BQ), schema)
        except SqlInputError as error:  # scripting: reported UNSUPPORTED, not a rewrite fault
            assert "unsupported construct" in str(error), str(error)
            continue
        assert "*" not in {t.name for t in db_tree.find_all(exp.Table)}


@pytest.mark.parametrize("task", REWRITTEN, ids=lambda t: t["id"])
def test_gold_and_candidate_get_the_same_rewrite_for_the_same_wildcard(task: dict) -> None:
    for item in task["rewrites"]:
        f, w = item["family_prefix"], item["wildcard_prefix"]
        derived = (
            f"AS _TABLE_SUFFIX FROM `{item['family_table']}` AS t "
            f"WHERE SUBSTR(CONCAT('{f}', t._shard), 1, {len(w)}) = '{w}')"
        )
        token = f"`{item['wildcard']}`"
        for side in ("gold", "candidate"):
            original = (DEMO / "original" / side / f"{task['id']}.sql").read_text("utf-8")
            rewritten = (DEMO / side / f"{task['id']}.sql").read_text("utf-8")
            # the same text replacement on each side: every wildcard token became one derived table
            assert rewritten.count(derived) == original.count(token)
            assert token not in rewritten


def test_the_rewrite_is_equivalent_to_a_wildcard_on_tiny_shards() -> None:
    """Three shards ``ev_20200101``, ``ev_20200102``, ``ev_20210101`` against the one-table form,
    for two wildcard prefixes of different length. The suffix, the filter and the rows agree."""
    con = duckdb.connect()
    shards = {"20200101": [(1, "a")], "20200102": [(2, "b"), (3, "c")], "20210101": [(4, "d")]}
    con.execute("CREATE TABLE ev (_shard VARCHAR NOT NULL, id BIGINT, s VARCHAR)")
    for suffix, rows in shards.items():
        for id_, s in rows:
            con.execute("INSERT INTO ev VALUES (?, ?, ?)", [suffix, id_, s])

    def wildcard(prefix: str) -> list[tuple]:
        """What BigQuery's ``ev_<prefix>*`` returns: matching shards, suffix after the prefix."""
        out = []
        for suffix, rows in shards.items():
            full = "ev_" + suffix
            if full.startswith("ev_" + prefix):
                out.extend((id_, s, full[len("ev_" + prefix) :]) for id_, s in rows)
        return sorted(out)

    ddl = "CREATE TABLE `p.d.ev` (_shard STRING NOT NULL, id INT64, s STRING)"
    schema = parse_warehouse_schema(ddl, BQ)
    for prefix in ("", "2020"):
        rewritten = (
            "SELECT id, s, _TABLE_SUFFIX AS suffix FROM "
            "(SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('ev_', t._shard), "
            f"{len('ev_' + prefix) + 1}) AS _TABLE_SUFFIX FROM `p.d.ev` AS t "
            f"WHERE SUBSTR(CONCAT('ev_', t._shard), 1, {len('ev_' + prefix)}) = 'ev_{prefix}')"
        )
        tree = resolve_tables(parse_query(rewritten, BQ), schema)
        got = sorted(con.execute(to_duckdb(tree, BQ, schema).sql).fetchall())
        assert got == wildcard(prefix), prefix
