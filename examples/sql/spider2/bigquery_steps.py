# Proposed fixture: pending owner review.
# Written by Claude and tested only against fake clients. NOTHING HERE HAS BEEN RUN ON BIGQUERY.
# The owner runs these steps (RUNBOOK-bigquery.md); each is one command with a bytes cap.
"""The 0.7 acceptance steps that need a BigQuery account.

Usage (from a checkout; each prints the bytes it used and writes a JSON file):

    python examples/sql/spider2/bigquery_steps.py smoke    --project P --out smoke.json
    python examples/sql/spider2/bigquery_steps.py smoke-detected --project P --out detected.json
    python examples/sql/spider2/bigquery_steps.py schema   --project P --out schema.json
    python examples/sql/spider2/bigquery_steps.py baseline --project P --spider2 DIR --out base.json
    python examples/sql/spider2/bigquery_steps.py rewrite  --project P --dataset D --out rw.json
    python examples/sql/spider2/bigquery_steps.py confirm  --project P --results DIR --out conf.json

Credentials: application-default credentials (``gcloud auth application-default login``) or
``GOOGLE_APPLICATION_CREDENTIALS``, read by Google's client library; never printed or written.

Every command takes ``--max-bytes-per-query`` and ``--max-bytes-total``. ``smoke``,
``smoke-detected`` (0.9: the fixtures the pack refuses, so a native outcome can be recorded),
``schema`` (metadata only), ``rewrite`` and ``confirm`` read no table data: they send inline text or
ask for
metadata. ``baseline`` reads public tables (dry runs first, caps enforced). ``rewrite`` is the one
step that writes to your project: it creates three tiny tables in the scratch dataset you name and
drops them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LABELS = {"isitright": "1", "isitright_phase": "runbook"}
MB = 1024 * 1024


class CapExceeded(RuntimeError):
    """A query's estimate is above the per-query cap, or the total would pass the total cap."""


class Runner:
    """Runs SQL on real tables or the scratch dataset: dry run first, caps, a running total."""

    def __init__(
        self,
        client: Any,
        *,
        config: Callable[..., Any],
        max_bytes_per_query: int,
        max_bytes_total: int,
        dry_run_only: bool = False,
        use_query_cache: bool = False,
    ) -> None:
        self.client, self.config = client, config
        self.use_query_cache = use_query_cache
        self.dry_run_only = dry_run_only
        self.last_estimate = 0
        self.per_query, self.total_cap = max_bytes_per_query, max_bytes_total
        self.estimated_total = 0
        self.billed_total = 0
        self.log: list[dict[str, Any]] = []

    def run(self, sql: str, *, timeout: float = 300.0) -> tuple[list[str], list[tuple[Any, ...]]]:
        options = {"use_query_cache": self.use_query_cache, "labels": dict(LABELS)}
        dry = self.client.query(sql, job_config=self.config(dry_run=True, **options))
        estimate = int(getattr(dry, "total_bytes_processed", 0) or 0)
        if estimate > self.per_query:
            raise CapExceeded(
                f"estimate {estimate} bytes is above the per-query cap {self.per_query}"
            )
        if self.estimated_total + estimate > self.total_cap:
            raise CapExceeded(f"the total would pass the cap {self.total_cap}")
        self.last_estimate = estimate
        if self.dry_run_only:  # print what it would cost; read nothing
            self.estimated_total += estimate
            self.log.append({"estimate": estimate, "billed": None, "dry_run_only": True})
            return [], []
        job = self.client.query(
            sql, job_config=self.config(maximum_bytes_billed=self.per_query, **options)
        )
        iterator = job.result(timeout=timeout)
        rows = list(iterator)
        # the row iterator has the result schema; a query job's own `schema` can still be empty
        schema = list(getattr(iterator, "schema", None) or getattr(job, "schema", None) or [])
        self.estimated_total += estimate
        self.billed_total += int(getattr(job, "total_bytes_billed", 0) or 0)
        self.log.append({"estimate": estimate, "billed": getattr(job, "total_bytes_billed", None)})
        names = [getattr(f, "name", f"f{i}") for i, f in enumerate(schema)]
        return names, [tuple(r.values()) if hasattr(r, "values") else tuple(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        return {
            "queries": len(self.log),
            "estimated_bytes": self.estimated_total,
            "billed_bytes": self.billed_total,
            "per_query_cap": self.per_query,
            "total_cap": self.total_cap,
        }


# --- step 2: smoke test ---------------------------------------------------------------------------


def smoke(host: Any, fixtures: list[Any] | None = None) -> dict[str, Any]:
    """Run the BigQuery fidelity fixtures with the state inlined and compare with the documented
    outcome. ``host`` is a `BigQueryHost` (or any `InlineHost`)."""
    sys.path.insert(0, str(ROOT))
    from isitright.packs.sql.dialects import get_dialect
    from isitright.packs.sql.inline import inline_sql
    from isitright.packs.sql.mapping import build_model
    from isitright.packs.sql.replaying import _state
    from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
    from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
    from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables
    from tests.warehouse_fixtures import BQ_DDL, BQ_ROWS, ERROR, FIXTURES

    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(BQ_DDL, dialect)
    state = _state(build_model(db, "bigquery"), BQ_ROWS)
    rows: list[dict[str, Any]] = []
    for fixture in fixtures if fixtures is not None else FIXTURES:
        if fixture.dialect != "bigquery" or fixture.status == "detected":
            continue
        tree = resolve_tables(parse_query(fixture.query, dialect), db)
        text = inline_sql(tree, dialect, db, state)
        try:
            result = host.run_inline(text, dialect, timeout_seconds=60, max_rows=100)
            observed: Any = [[cell.value for cell in row] for row in result.rows]
        except QueryExecutionError as error:
            observed, detail = ERROR, str(error)[:200]
        else:
            detail = ""
        expected = fixture.native

        def same_rows(value: Any, ordered: bool = fixture.ordered) -> Any:
            if isinstance(value, list) and not ordered:
                return sorted(value, key=repr)
            return value

        if expected is None:
            outcome = "no documented outcome"
        elif same_rows(observed) == same_rows(expected):
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
                "detail": detail,
            }
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    return {"fixtures": rows, "counts": counts, "host_records": getattr(host, "records", [])}


def smoke_detected(host: Any, fixtures: list[Any] | None = None) -> dict[str, Any]:
    """Send the ``detected`` BigQuery fixtures, which the pack refuses, with the state inlined.

    The pack refuses them because DuckDB cannot emulate them; this asks whether BigQuery runs them
    and what it returns, so the fixture can record a native outcome. The text is inlined without the
    pack's query parser (which is what refuses the construct) and goes through the same host, so
    the refusal of a real table, the dry run and the byte cap still apply. A fixture that cannot be
    inlined (a wildcard table names real shard tables) is reported as not sent, with the reason.
    """
    sys.path.insert(0, str(ROOT))
    import sqlglot

    from isitright.packs.sql.dialects import get_dialect
    from isitright.packs.sql.errors import SqlInputError
    from isitright.packs.sql.inline import inline_sql
    from isitright.packs.sql.mapping import build_model
    from isitright.packs.sql.native import NativeHostError
    from isitright.packs.sql.replaying import _state
    from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
    from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
    from isitright.packs.sql.warehouse_sql import resolve_tables
    from tests.warehouse_fixtures import BQ_DDL, BQ_ROWS, ERROR, FIXTURES

    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(BQ_DDL, dialect)
    state = _state(build_model(db, "bigquery"), BQ_ROWS)
    rows: list[dict[str, Any]] = []
    for fixture in fixtures if fixtures is not None else FIXTURES:
        if fixture.dialect != "bigquery" or fixture.status != "detected":
            continue
        row: dict[str, Any] = {"id": fixture.id, "query": fixture.query}
        try:
            tree = resolve_tables(sqlglot.parse_one(fixture.query, read=dialect.read), db)
            text = inline_sql(tree, dialect, db, state)
        except SqlInputError as error:
            row.update(outcome="not sent", reason=f"cannot be inlined: {error}")
            rows.append(row)
            continue
        try:
            result = host.run_inline(text, dialect, timeout_seconds=60, max_rows=100)
        except NativeHostError as error:  # the host could not run it: no outcome either way
            row.update(outcome="not run", reason=str(error)[:200])
        except QueryExecutionError as error:
            row.update(outcome="observed", observed_native=ERROR, detail=str(error)[:200])
        else:
            observed = [[cell.value for cell in r] for r in result.rows]
            row.update(outcome="observed", observed_native=observed, detail="")
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    return {"fixtures": rows, "counts": counts, "host_records": getattr(host, "records", [])}


# --- step 3: schema check -------------------------------------------------------------------------


def schema_check(runner: Runner, demo: Path = HERE) -> dict[str, Any]:
    """Compare Spider's DDL with the live INFORMATION_SCHEMA for every table the tasks read."""
    sys.path.insert(0, str(ROOT / "src"))
    from isitright.packs.sql.dialects import get_dialect
    from isitright.packs.sql.errors import SqlInputError
    from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema

    dialect = get_dialect("bigquery")
    findings: list[dict[str, Any]] = []
    cache: dict[str, dict[str, str]] = {}
    for line in (demo / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        task = json.loads(line)
        try:
            schema = parse_warehouse_schema(
                (demo / "ddl" / f"{task['id']}.sql").read_text(encoding="utf-8"), dialect
            )
        except SqlInputError:
            continue  # reported UNSUPPORTED by the audit
        families = {
            w["family_table"].rpartition(".")[2]: w["family_prefix"] for w in task["rewrites"]
        }
        for table in schema.tables:
            project, _, rest = (table.qualified or table.name).partition(".")
            dataset, _, name = rest.rpartition(".")
            key = f"{project}.{dataset}.{name}"
            if key not in cache:
                match = (
                    f"STARTS_WITH(table_name, '{families[name]}')"
                    if name in families
                    else f"table_name = '{name}'"
                )
                try:
                    _, live = runner.run(
                        "SELECT column_name, data_type FROM "
                        f"`{project}.{dataset}`.INFORMATION_SCHEMA.COLUMNS WHERE {match}"
                    )
                except CapExceeded:
                    raise
                except Exception as error:  # e.g. no access to that dataset: report it
                    findings.append(
                        {
                            "task": task["id"],
                            "table": key,
                            "error": f"{type(error).__name__}: {str(error)[:160]}",
                        }
                    )
                    cache[key] = {}
                    continue
                cache[key] = {str(r[0]): str(r[1]) for r in live}
            live_columns = cache[key]
            spider_columns = {c.name for c in table.columns} - (
                {"_shard"} if name in families else set()
            )
            missing = sorted(spider_columns - set(live_columns))
            added = sorted(set(live_columns) - spider_columns)
            if missing or added or not live_columns:
                findings.append(
                    {
                        "task": task["id"],
                        "table": key,
                        "family": name in families,
                        "table_found": bool(live_columns),
                        "columns_missing_live": missing,
                        "columns_new_live": added,
                    }
                )
    return {"differences": findings, "tables_checked": len(cache), **runner.summary()}


def _read_csv(path: Path) -> list[list[str]]:
    import csv

    csv.field_size_limit(10**9)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [[cell[:60] for cell in row] for row in csv.reader(handle)]


def _read_csv_full(path: Path) -> list[list[str]]:
    import csv

    csv.field_size_limit(10**9)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [list(row) for row in csv.reader(handle)]


def _sample(result: tuple[list[str], list[tuple[Any, ...]]], rows: int = 3) -> dict[str, Any]:
    names, data = result
    return {
        "columns": names,
        "rows": [[f"{type(v).__name__}:{str(v)[:60]}" for v in row] for row in data[:rows]],
    }


# --- step 4: baseline ---------------------------------------------------------------------------


def baseline(
    runner: Runner, spider2: Path, demo: Path = HERE, only: list[str] | None = None
) -> dict[str, Any]:
    """Run each task's gold and candidate SQL (the ORIGINAL, not the rewritten) once on the public
    data and keep the pairs that match under the task's comparison. Spider's gold result is read
    from ``spider2`` only to cross-check the gold run."""
    sys.path.insert(0, str(ROOT / "src"))
    from isitright.packs.sql.comparison import compare_results
    from isitright.packs.sql.models import (
        CanonicalValue,
        CanonicalValueKind,
        ColumnComparisonPolicy,
        ComparisonPolicy,
        OrderingPolicy,
        QueryResult,
        ResultColumn,
    )

    def canonical(value: Any) -> CanonicalValue:
        if value is None:
            return CanonicalValue(kind=CanonicalValueKind.NULL, value=None)
        if isinstance(value, bool):
            return CanonicalValue(kind=CanonicalValueKind.BOOLEAN, value=value)
        if isinstance(value, int):
            return CanonicalValue(kind=CanonicalValueKind.INTEGER, value=value)
        if isinstance(value, float):
            return CanonicalValue(kind=CanonicalValueKind.FLOAT, value=value)
        if isinstance(value, Decimal):  # NUMERIC: a number, not text, so a FLOAT64 column can match
            return CanonicalValue(kind=CanonicalValueKind.DECIMAL, value=str(value))
        return CanonicalValue(kind=CanonicalValueKind.TEXT, value=str(value))

    def as_result(names: list[str], rows: list[tuple[Any, ...]]) -> QueryResult:
        return QueryResult(
            columns=[ResultColumn(name=n) for n in names],
            rows=[[canonical(v) for v in row] for row in rows],
        )

    def result_vs_files(
        task: dict[str, Any], result: Any, csv_files: list[Path]
    ) -> tuple[list[str], list[str]]:
        """The Spider result files ``result`` matches, each under its own ``condition_cols`` (the
        way Spider scores a prediction), and the files the comparison could not read."""
        cols = task["condition_cols"]
        variants = cols if cols and all(isinstance(c, list) for c in cols) else [cols]
        matched: list[str] = []
        problems: list[str] = []
        for index, path in enumerate(csv_files):
            variant = (
                variants[index] if len(variants) > 1 and index < len(variants) else variants[0]
            )
            rows = _read_csv_full(path)
            if not rows:
                continue
            reference = QueryResult(
                columns=[ResultColumn(name=n) for n in rows[0]],
                rows=[
                    [
                        CanonicalValue(kind=CanonicalValueKind.NULL, value=None)
                        if cell == ""
                        else CanonicalValue(kind=CanonicalValueKind.TEXT, value=cell)
                        for cell in row
                    ]
                    for row in rows[1:]
                ],
            )
            policy = ComparisonPolicy(
                columns=ColumnComparisonPolicy.CONTAINED,
                ordering=OrderingPolicy.UNORDERED
                if task["ignore_order"]
                else OrderingPolicy.ORDERED,
                null_as_zero=True,
                float_absolute_tolerance=0.01,
                reference_columns=[int(c) for c in variant] or None,
            )
            try:
                if compare_results(reference, as_result(*result), policy=policy).matches:
                    matched.append(path.name)
            except Exception as error:  # a file this comparison cannot read is not a match
                problems.append(f"{path.name}: {type(error).__name__}")
        return matched, problems

    def gold_vs_files(task: dict[str, Any], gold: Any, csv_files: list[Path]) -> dict[str, Any]:
        """Is the gold SQL trustworthy as a reference? Only if its result on today's data equals one
        of Spider's published result files. The files are what the benchmark scores; the SQL is
        not."""
        if not csv_files:
            return {"gold_trusted": None, "gold_trust_basis": "no Spider result file for the task"}
        matched, problems = result_vs_files(task, gold, csv_files)
        basis = (
            f"the gold SQL's result on the real data equals Spider's result file {matched[0]}"
            if matched
            else f"the gold SQL's result on the real data equals none of Spider's {len(csv_files)} "
            "result files (the data may have changed since the files were made, or the gold SQL "
            "is not the query behind them)"
        )
        out: dict[str, Any] = {"gold_matches_spider_files": matched, "gold_trusted": bool(matched)}
        out["gold_trust_basis"] = basis
        if problems:
            out["gold_vs_files_problems"] = problems
        return out

    spider_gold = spider2 / "spider2-lite" / "evaluation_suite" / "gold" / "exec_result"
    if not runner.dry_run_only and not spider_gold.is_dir():
        raise SystemExit(f"{spider_gold} not found: --spider2 must be the Spider2 checkout")
    out: list[dict[str, Any]] = []
    for line in (demo / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        task = json.loads(line)
        if only and task["id"] not in only:
            continue
        entry: dict[str, Any] = {"id": task["id"]}
        if runner.dry_run_only:
            try:
                runner.run((demo / "original" / "gold" / f"{task['id']}.sql").read_text("utf-8"))
                entry["gold_estimate"] = runner.last_estimate
                runner.run(
                    (demo / "original" / "candidate" / f"{task['id']}.sql").read_text("utf-8")
                )
                entry["candidate_estimate"] = runner.last_estimate
            except Exception as error:
                entry["error"] = f"{type(error).__name__}: {str(error)[:160]}"
            out.append(entry)
            continue
        try:
            gold = runner.run((demo / "original" / "gold" / f"{task['id']}.sql").read_text("utf-8"))
            cand = runner.run(
                (demo / "original" / "candidate" / f"{task['id']}.sql").read_text("utf-8")
            )
        except CapExceeded as error:
            entry["skipped"] = str(error)
            out.append(entry)
            continue
        except Exception as error:
            entry["error"] = f"{type(error).__name__}: {str(error)[:200]}"
            out.append(entry)
            continue
        if not gold[0] or not cand[0]:
            entry["error"] = "a query returned no column names; not compared"
            out.append(entry)
            continue
        entry.update(gold_vs_files(task, gold, sorted(spider_gold.glob(f"{task['id']}*.csv"))))
        # Spider keeps one gold result per accepted variant (`_a`, `_b`, ...) with its own
        # `condition_cols`; a prediction passes if it matches any. Only the gold SQL's own result is
        # available here, so try each list that fits its columns and keep the pair if one matches.
        cols = task["condition_cols"]
        variants = cols if cols and all(isinstance(c, list) for c in cols) else [cols]
        fitting = [v for v in variants if all(0 <= int(c) < len(gold[0]) for c in v)]
        entry["condition_cols_lists_fitting"] = f"{len(fitting)} of {len(variants)}"
        if not fitting:
            entry["error"] = f"no condition_cols list fits the gold's {len(gold[0])} columns"
            out.append(entry)
            continue
        match = None
        try:
            for variant in fitting:
                policy = ComparisonPolicy(
                    columns=ColumnComparisonPolicy.CONTAINED,
                    ordering=(
                        OrderingPolicy.UNORDERED if task["ignore_order"] else OrderingPolicy.ORDERED
                    ),
                    null_as_zero=True,
                    float_absolute_tolerance=0.01,
                    reference_columns=[int(c) for c in variant] or None,
                )
                match = compare_results(as_result(*gold), as_result(*cand), policy=policy)
                if match.matches:
                    entry["matched_condition_cols"] = variant
                    break
        except Exception as error:  # one task's comparison must not lose the other tasks' runs
            entry["error"] = f"comparison: {type(error).__name__}: {str(error)[:200]}"
            out.append(entry)
            continue
        assert match is not None
        entry["pair_matches_under_task_settings"] = match.matches
        entry["difference"] = match.difference
        entry["gold_rows"], entry["candidate_rows"] = len(gold[1]), len(cand[1])
        csv_files = sorted(spider_gold.glob(f"{task['id']}*.csv"))
        # 0.9: where the gold SQL does not reproduce any of Spider's files, the files are the
        # reference on the real data (Spider accepts a candidate that matches any of them).
        cand_files, cand_problems = result_vs_files(task, cand, csv_files)
        entry["candidate_matches_spider_files"] = cand_files
        if cand_problems:
            entry["candidate_vs_files_problems"] = cand_problems
        if entry.get("gold_trusted") is False:
            entry["baseline_reference"] = "Spider's result files (the gold SQL matches none)"
            entry["baseline_agrees"] = bool(cand_files)
        else:
            entry["baseline_reference"] = "the gold SQL" + (
                "" if entry.get("gold_trusted") else " (no Spider result file to check it)"
            )
            entry["baseline_agrees"] = match.matches
        entry["spider_gold_result_files"] = [p.name for p in csv_files]
        csv_rows = [_read_csv(p) for p in csv_files]
        # Spider keeps one gold result per accepted variant; the gold SQL should match one of them
        entry["spider_gold_row_counts"] = [max(len(r) - 1, 0) for r in csv_rows]
        entry["gold_row_count_equals_spider_gold_csv"] = (
            len(gold[1]) in entry["spider_gold_row_counts"] if csv_rows else None
        )
        if not match.matches or entry["gold_row_count_equals_spider_gold_csv"] is False:
            # public data, small samples: enough to read why two results are called different
            entry["gold_sample"] = _sample(gold)
            entry["candidate_sample"] = _sample(cand)
            entry["spider_gold_csv_samples"] = [r[:4] for r in csv_rows]
        out.append(entry)
    kept = [e["id"] for e in out if e.get("baseline_agrees")]
    gold_sql_kept = [e["id"] for e in out if e.get("pair_matches_under_task_settings")]
    return {
        "tasks": out,
        "kept_pairs": kept,
        "kept": len(kept),
        "kept_with_gold_sql_as_reference": len(gold_sql_kept),
        **runner.summary(),
    }


# --- step 5: wildcard rewrite equivalence ---------------------------------------------------------


def rewrite_equivalence(runner: Runner, project: str, dataset: str) -> dict[str, Any]:
    """Three tiny shard tables in a scratch dataset: an original wildcard query against the rewrite.
    This is the only step that writes to a project. The tables are dropped at the end."""
    prefix = f"isitright_ev_{int(time.time())}_"
    shards = {"20200101": [(1, "a")], "20200102": [(2, "b"), (3, "c")], "20210101": [(4, "d")]}
    # not under `prefix`: an empty-prefix wildcard would match the family table as well
    family = f"isitright_evfamily_{int(time.time())}"
    created: list[str] = []
    results: list[dict[str, Any]] = []
    try:
        for suffix, rows in shards.items():
            name = f"{prefix}{suffix}"
            structs = ", ".join(f"STRUCT({i} AS id, '{s}' AS s)" for i, s in rows)
            runner.run(
                f"CREATE TABLE `{project}.{dataset}.{name}` AS SELECT * FROM UNNEST([{structs}])"
            )
            created.append(name)
        union = " UNION ALL ".join(
            f"SELECT '{suffix}' AS _shard, id, s FROM `{project}.{dataset}.{prefix}{suffix}`"
            for suffix in shards
        )
        runner.run(f"CREATE TABLE `{project}.{dataset}.{family}` AS {union}")
        created.append(family)
        for wildcard_prefix in ("", "2020"):
            original = (
                "SELECT id, s, _TABLE_SUFFIX AS suffix FROM "
                f"`{project}.{dataset}.{prefix}{wildcard_prefix}*`"
            )
            width = len(prefix + wildcard_prefix)
            rewritten = (
                "SELECT id, s, _TABLE_SUFFIX AS suffix FROM (SELECT t.* EXCEPT (_shard), "
                f"SUBSTR(CONCAT('{prefix}', t._shard), {width + 1}) AS _TABLE_SUFFIX "
                f"FROM `{project}.{dataset}.{family}` AS t "
                f"WHERE SUBSTR(CONCAT('{prefix}', t._shard), 1, {width}) = "
                f"'{prefix}{wildcard_prefix}')"
            )
            left = sorted(runner.run(original)[1], key=repr)
            right = sorted(runner.run(rewritten)[1], key=repr)
            check = {"wildcard_prefix": wildcard_prefix, "equal": left == right, "rows": len(left)}
            if left != right:  # small tables: show both sides so the difference can be read
                check["wildcard_rows"] = [list(r) for r in left]
                check["rewrite_rows"] = [list(r) for r in right]
            results.append(check)
    finally:
        for name in created:
            try:
                runner.run(f"DROP TABLE IF EXISTS `{project}.{dataset}.{name}`")
            except Exception as error:  # report it; the owner can drop the table by hand
                results.append({"drop_failed": name, "error": str(error)[:120]})
    left_behind = [r["drop_failed"] for r in results if "drop_failed" in r]
    return {
        "checks": results,
        "all_equal": all(r["equal"] for r in results if "equal" in r)
        and any("equal" in r for r in results),
        "cleanup_ok": not left_behind,
        "tables_left_behind": left_behind,  # drop these by hand
        **runner.summary(),
    }


# --- step 6: confirm the emulated findings -------------------------------------------------


def confirm(host: Any, results_dir: Path, demo: Path = HERE) -> dict[str, Any]:
    """Re-run each task with an emulated finding on the BigQuery host (same seed, same finding)."""
    sys.path.insert(0, str(ROOT / "src"))
    from isitright.packs.sql import CheckConfig, check
    from isitright.packs.sql.constraints_file import load_constraint_schema
    from isitright.packs.sql.models import ColumnComparisonPolicy, OrderingPolicy

    sys.path.insert(0, str(HERE))
    import run_demo

    task_ids = [
        json.loads(line)["id"]
        for line in (demo / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if not results_dir.is_dir() or not any((results_dir / f"{i}.json").exists() for i in task_ids):
        raise SystemExit(
            f"no task records (<id>.json) in {results_dir}: copy the results-final folder of the "
            "demo run there, or point --results at it"
        )
    out: list[dict[str, Any]] = []
    for line in (demo / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        task = json.loads(line)
        summary_file = results_dir / f"{task['id']}.json"
        if not summary_file.exists():
            continue
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        for label in ("benchmark", "strict"):
            if summary.get(label, {}).get("status") != "COUNTEREXAMPLE_FOUND":
                continue
            ordering = OrderingPolicy.UNORDERED if task["ignore_order"] else OrderingPolicy.ORDERED
            variants = run_demo.reference_column_variants(task["condition_cols"])
            recorded = summary[label].get("finding") or {}
            # the benchmark verdict came from one variant's audit: confirm that variant's finding
            found_by = summary[label].get("found_by_index", 0) if label == "benchmark" else None
            config = (
                CheckConfig(
                    column_policy=ColumnComparisonPolicy.CONTAINED,
                    null_as_zero=True,
                    float_absolute_tolerance=0.01,
                    ordering_policy=ordering,
                    reference_columns=variants[found_by or 0],
                    wall_time_seconds=summary["settings"]["wall_time_cap_seconds"],
                )
                if label == "benchmark"
                else CheckConfig(wall_time_seconds=summary["settings"]["wall_time_cap_seconds"])
            )
            constraints_path = demo / "constraints" / f"{task['id']}.yaml"
            report = check(
                reference_sql=(demo / "gold" / f"{task['id']}.sql").read_text("utf-8"),
                candidate_sql=(demo / "candidate" / f"{task['id']}.sql").read_text("utf-8"),
                dialect="bigquery",
                ddl=(demo / "ddl" / f"{task['id']}.sql").read_text("utf-8"),
                question=task["question"],
                case_id=task["id"],
                constraints=load_constraint_schema(constraints_path)
                if constraints_path.exists()
                else None,
                config=config,
                confirm=host,
            )
            finding = report.findings[0] if report.findings else None
            same_world = None
            native_outcomes = None
            if finding is not None and recorded.get("state_sha"):
                same_world = (
                    run_demo.state_sha(finding.divergence["candidate_state"])
                    == recorded["state_sha"]
                )
            native = finding.divergence.get("native_results") if finding else None
            if label == "benchmark" and native:
                # the complete acceptance rule, on the native engine's own results
                native_outcomes = run_demo.variant_outcomes(
                    native["reference_result"],
                    native["candidate_result"],
                    variants,
                    task["ignore_order"],
                )
            out.append(
                {
                    "id": task["id"],
                    "comparison": label,
                    "found_by": summary[label].get("found_by") if label == "benchmark" else None,
                    "same_world_as_recorded": same_world,
                    "native_variant_outcomes": native_outcomes,
                    "status": report.divergence_status.value,
                    "verified_on": finding.fidelity.verified_on if finding else None,
                    "verification": finding.fidelity.verification.model_dump()
                    if finding and finding.fidelity.verification
                    else None,
                    "emulation_artifacts": report.extensions["sql"].get("emulation_artifact_count"),
                    "native_confirmation": finding.divergence.get("native_confirmation")
                    if finding
                    else None,
                }
            )
    for e in out:  # a confirmation counts only for the recorded world and, for the benchmark, if
        # no accepted list takes the native result
        e["confirms_recorded_finding"] = (
            e["verified_on"] == "NATIVE_INLINE"
            and e["same_world_as_recorded"] is not False
            and (
                e["native_variant_outcomes"] is None
                or set(e["native_variant_outcomes"]) == {"rejects"}
            )
        )
    verified = sum(1 for e in out if e["confirms_recorded_finding"])
    return {
        "confirmations": out,
        "verified": verified,
        "total": len(out),
        "host_records": getattr(host, "records", []),
    }


# --- command line ----------------------------------------------------------------------------


def _client(project: str) -> tuple[Any, Callable[..., Any]]:
    from google.cloud import bigquery  # the isitright[bigquery] extra

    return bigquery.Client(project=project), bigquery.QueryJobConfig


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "step", choices=["smoke", "smoke-detected", "schema", "baseline", "rewrite", "confirm"]
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset", help="scratch dataset for the rewrite step")
    parser.add_argument("--spider2", type=Path, help="Spider2 checkout (baseline cross-check)")
    parser.add_argument("--results", type=Path, help="results directory of run_demo.py (confirm)")
    parser.add_argument("--only", help="comma-separated task ids (baseline)")
    parser.add_argument(
        "--dry-run-only", action="store_true", help="baseline: estimate, read nothing"
    )
    parser.add_argument("--max-bytes-per-query", type=int, default=2 * 1024**3)
    parser.add_argument("--max-bytes-total", type=int, default=20 * 1024**3)
    args = parser.parse_args(argv)
    client, config = _client(args.project)
    sys.path.insert(0, str(ROOT / "src"))
    if args.step in ("smoke", "smoke-detected", "confirm"):
        from isitright.packs.sql.native import BigQueryHost

        host = BigQueryHost(
            project=args.project, max_bytes_billed=min(args.max_bytes_per_query, 100 * MB)
        )
        if args.step == "smoke":
            result = smoke(host)
        elif args.step == "smoke-detected":
            result = smoke_detected(host)
        else:
            result = confirm(host, args.results)
    else:
        runner = Runner(
            client,
            config=config,
            max_bytes_per_query=args.max_bytes_per_query,
            max_bytes_total=args.max_bytes_total,
            dry_run_only=args.dry_run_only,
            use_query_cache=args.step == "baseline",  # a rerun inside 24 h reads BigQuery's cache
        )
        if args.step == "schema":
            result = schema_check(runner)
        elif args.step == "baseline":
            only = args.only.split(",") if args.only else None
            result = baseline(runner, args.spider2, only=only)
        else:
            result = rewrite_equivalence(runner, args.project, args.dataset)
    args.out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in (
                    "fixtures",
                    "tasks",
                    "confirmations",
                    "differences",
                    "checks",
                    "host_records",
                )
            },
            default=str,
        )
    )
    if result.get("tables_left_behind"):
        names = ", ".join(result["tables_left_behind"])
        print(
            f"CLEANUP FAILED: drop these scratch tables by hand in {args.project}.{args.dataset}: "
            f"{names}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
