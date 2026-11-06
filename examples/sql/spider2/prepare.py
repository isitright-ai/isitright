# Proposed fixture: pending owner review.
# Written by Claude. The gold SQL is Spider 2.0's and the candidate SQL is schemagate's (Claude
# Sonnet 5.5); this script writes neither. It selects tasks by a rule fixed before any audit ran,
# copies what the demo needs, and applies ONE mechanical rewrite (wildcard tables) identically to
# gold and candidate, keeping the originals beside the rewrites.
"""Prepare the Spider 2.0-lite BigQuery demo data from two local clones (read only).

Usage: python -I prepare.py <Spider2 checkout> <schemagate checkout> <output directory>

Nothing from either repository is executed. The output directory gets: ``tasks.jsonl`` (one record
per selected task), ``gold/`` and ``candidate/`` (the SQL after the wildcard rewrite),
``original/gold`` and ``original/candidate`` (as published), ``ddl/`` (the tables each task reads),
``external_knowledge/``, ``selection.json`` and the licence texts. Spider's gold *result* files
are not copied and never read.

The wildcard rewrite. BigQuery's ``FROM `p.d.PREFIX*` `` reads every table whose name starts with
PREFIX and exposes the rest of the name as ``_TABLE_SUFFIX``. In the demo copy a family of
shard tables (same columns, names ``F`` + a suffix) is one table ``<family>`` with an extra column
``_shard`` holding the suffix after ``F``, and the reference becomes a derived table that computes
``_TABLE_SUFFIX`` per reference from ``F || _shard``. The same text replacement is applied to gold
and candidate, so prefixes of different lengths map to one family.
"""

from __future__ import annotations

import ast
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import sqlglot
from sqlglot import exp

csv.field_size_limit(10**9)
RUN = "benchmarks/results/spider2_lite_bigquery"
MODEL = "claude-sonnet-5-5"
BACKTICKED = re.compile(r"`([^`]+)`")


def git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def select(spider: Path, schemagate: Path) -> dict:
    run = schemagate / RUN
    with (run / f"{MODEL}.correct_ids.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [r[0] for r in csv.reader(handle) if r]
    csv_ids = {re.sub(r"^sf_", "", i) for i in rows[1:]}
    text = (run / f"{MODEL}.eval.txt").read_text(encoding="utf-8-sig", errors="replace")
    scores = next(
        ast.literal_eval(line) for line in text.splitlines() if line.startswith("{'bq001'")
    )
    assert csv_ids == {i for i, s in scores.items() if s == 1}
    gold_dir = spider / "spider2-lite" / "evaluation_suite" / "gold" / "sql"
    gold = {p.stem for p in gold_dir.glob("*.sql") if re.match(r"^(bq|ga)\d+$", p.stem)}
    ids = sorted(csv_ids & gold)
    tasks = {}
    with (spider / "spider2-lite" / "spider2-lite.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line)
            tasks[entry["instance_id"]] = entry
    settings = {}
    with (spider / "spider2-lite" / "evaluation_suite" / "gold" / "spider2lite_eval.jsonl").open(
        encoding="utf-8"
    ) as handle:
        for line in handle:
            entry = json.loads(line)
            settings[entry["instance_id"]] = entry
    return {
        "rule": "BigQuery tasks (bq*, ga*) of Spider 2.0-lite with published gold SQL that "
        "schemagate's run marks correct (Spider 2.0's evaluator, exec_result mode)",
        "spider2_commit": git_head(spider),
        "schemagate_commit": git_head(schemagate),
        "model": MODEL,
        "counts": {
            "correct_in_schemagate_run": len(csv_ids),
            "bigquery_tasks_with_published_gold": len(gold),
            "selected": len(ids),
        },
        "task_ids": ids,
        "tasks": {i: (tasks[i], settings[i]) for i in ids},
    }


def load_ddls(spider: Path, db: str) -> dict[str, str]:
    """``project.dataset.table -> CREATE TABLE text`` for every table of a Spider database."""
    out: dict[str, str] = {}
    base = spider / "spider2-lite" / "resource" / "databases" / "bigquery" / db
    for ddl_csv in sorted(base.glob("*/DDL.csv")):
        dataset = ddl_csv.parent.name  # project.dataset
        with ddl_csv.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                out[f"{dataset}.{row['table_name']}"] = row["ddl"]
    return out


def lcp(names: list[str]) -> str:
    first, last = min(names), max(names)
    n = 0
    while n < len(first) and n < len(last) and first[n] == last[n]:
        n += 1
    return first[:n]


def family_name(prefix: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", prefix.rstrip("_"))
    return name if name and not name[0].isdigit() else f"shards_{name}"


def columns_of(ddl: str) -> str:
    """The column list of a CREATE TABLE, for comparing shards (names and types, not options)."""
    tree = sqlglot.parse_one(ddl, read="bigquery")
    return ";".join(
        f"{c.name}:{c.args['kind'].sql('bigquery')}"
        for c in tree.find_all(exp.ColumnDef)
        if c.parent is tree.this
    )


def table_refs(sql: str) -> tuple[list[str], str | None]:
    """Backticked dotted names in the text (what Spider's queries use), and a parse error if any."""
    names = [m.group(1) for m in BACKTICKED.finditer(sql) if "." in m.group(1) or "*" in m.group(1)]
    try:
        sqlglot.parse_one(sql, read="bigquery")
        return names, None
    except Exception as error:
        return names, f"{type(error).__name__}: {str(error)[:120]}"


def main(spider: Path, schemagate: Path, out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise SystemExit("the output directory must be new or empty")
    selection = select(spider, schemagate)
    for sub in (
        "gold",
        "candidate",
        "original/gold",
        "original/candidate",
        "ddl",
        "external_knowledge",
        "licenses",
    ):
        (out / sub).mkdir(parents=True, exist_ok=True)
    gold_src = spider / "spider2-lite" / "evaluation_suite" / "gold" / "sql"
    cand_src = schemagate / RUN / MODEL
    docs = spider / "spider2-lite" / "resource" / "documents"
    records = []
    ddl_cache: dict[str, dict[str, str]] = {}
    for task_id in selection["task_ids"]:
        entry, setting = selection["tasks"][task_id]
        db = entry["db"]
        tables = ddl_cache.setdefault(db, load_ddls(spider, db))
        gold = (gold_src / f"{task_id}.sql").read_text(encoding="utf-8")
        cand = (cand_src / f"{task_id}.sql").read_text(encoding="utf-8")
        (out / "original" / "gold" / f"{task_id}.sql").write_text(gold, encoding="utf-8")
        (out / "original" / "candidate" / f"{task_id}.sql").write_text(cand, encoding="utf-8")
        refs: dict[str, str] = {}
        parse_errors = {}
        for label, sql in (("gold", gold), ("candidate", cand)):
            names, error = table_refs(sql)
            if error:
                parse_errors[label] = error
            for n in names:
                refs[n] = n
        statements: list[str] = []
        rewrites: list[dict] = []
        unresolved: list[str] = []
        used_tables: list[str] = []
        families: dict[str, dict] = {}
        for ref in sorted(refs):
            if "*" in ref:
                head, _, prefix_star = ref.rpartition(".")
                wanted = prefix_star.rstrip("*")
                dataset = head
                shards = sorted(
                    n
                    for n in tables
                    if n.startswith(dataset + ".") and n.rpartition(".")[2].startswith(wanted)
                )
                if not shards:
                    unresolved.append(ref)
                    continue
                short = [s.rpartition(".")[2] for s in shards]
                newest = shards[-1]
                newest_names = {c.partition(":")[0] for c in columns_of(tables[newest]).split(";")}
                older_extra = {
                    c.partition(":")[0] for s in shards for c in columns_of(tables[s]).split(";")
                } - newest_names
                if older_extra:
                    unresolved.append(
                        f"{ref} (shards are not one table over time: {sorted(older_extra)[:3]} "
                        "are missing from the newest shard)"
                    )
                    continue
                drift = len({columns_of(tables[s]) for s in shards}) > 1
                f = (
                    lcp(short).rstrip("0123456789")
                    if len(short) > 1
                    else short[0].rstrip("0123456789")
                )
                fam = family_name(f)
                full = f"{dataset}.{fam}"
                suffixes = [s[len(f) :] for s in short]
                if full not in families:
                    rep = tables[newest]
                    old_name = f"`{newest}`"
                    assert old_name in rep, (task_id, newest)
                    text = rep.replace(old_name, f"`{full}`", 1)
                    text = text.replace(
                        "(\n",
                        '(\n  _shard STRING NOT NULL OPTIONS(description="suffix of the shard name '
                        'after the family prefix"),\n',
                        1,
                    )
                    families[full] = {
                        "family": fam,
                        "prefix": f,
                        "ddl": text,
                        "shards": len(shards),
                        "drift": drift,
                    }
                rewrites.append(
                    {
                        "wildcard": ref,
                        "family_table": full,
                        "family_prefix": f,
                        "wildcard_prefix": wanted,
                        "shards": len(shards),
                        "example_suffix": suffixes[0],
                        "schema_drift": drift,
                    }
                )
            else:
                matches = [n for n in tables if n == ref or n.endswith("." + ref)]
                if len(matches) == 1:
                    used_tables.append(matches[0])
                elif ref in tables:
                    used_tables.append(ref)
                else:
                    unresolved.append(ref)
        for table in sorted(set(used_tables)):
            statements.append(tables[table].rstrip().rstrip(";") + ";")
        for _full, fam in sorted(families.items()):
            statements.append(fam["ddl"].rstrip().rstrip(";") + ";")

        def rewrite(sql: str, rewrites: list[dict] = rewrites) -> str:
            for item in rewrites:
                token = f"`{item['wildcard']}`"
                f, w = item["family_prefix"], item["wildcard_prefix"]
                derived = (
                    f"(SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('{f}', t._shard), {len(w) + 1}) "
                    f"AS _TABLE_SUFFIX FROM `{item['family_table']}` AS t "
                    f"WHERE SUBSTR(CONCAT('{f}', t._shard), 1, {len(w)}) = '{w}')"
                )
                sql = sql.replace(token, derived)
            return sql

        (out / "gold" / f"{task_id}.sql").write_text(rewrite(gold), encoding="utf-8")
        (out / "candidate" / f"{task_id}.sql").write_text(rewrite(cand), encoding="utf-8")
        (out / "ddl" / f"{task_id}.sql").write_text(
            "\n\n".join(statements) + "\n", encoding="utf-8"
        )
        knowledge = entry.get("external_knowledge")
        if knowledge and (docs / knowledge).is_file():
            shutil.copyfile(docs / knowledge, out / "external_knowledge" / knowledge)
        records.append(
            {
                "id": task_id,
                "db": db,
                "question": entry["question"],
                "external_knowledge": knowledge,
                "condition_cols": setting.get("condition_cols"),
                "ignore_order": setting.get("ignore_order", False),
                "tables": sorted(set(used_tables)),
                "rewrites": rewrites,
                "unresolved_tables": unresolved,
                "parse_errors": parse_errors,
            }
        )
    with (out / "tasks.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    public = {k: v for k, v in selection.items() if k != "tasks"}
    (out / "selection.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(spider / "LICENSE", out / "licenses" / "Spider2-MIT.txt")
    shutil.copyfile(schemagate / "LICENSE", out / "licenses" / "schemagate-Apache-2.0.txt")
    for name in (f"{MODEL}.correct_ids.csv", f"{MODEL}.eval.txt", "README.md"):
        shutil.copyfile(schemagate / RUN / name, out / "licenses" / f"schemagate-run-{name}")
    print(json.dumps(selection["counts"]), f"{len(records)} records")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
