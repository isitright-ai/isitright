# Proposed fixture: pending owner review.
# Written by Claude. The comparison settings per task come from Spider's own evaluation settings
# (condition_cols, ignore_order) and are fixed by the rules below, not chosen by what they find.
"""Audit the selected Spider 2.0-lite BigQuery tasks, schema only, on DuckDB.

Usage:
    python -I run_demo.py <output directory> [--only bq001,ga002] [--cap 600]   # all tasks
    python -I run_demo.py <output directory> --nested-scope column            # 0.7 scoping
    python -I run_demo.py <output directory> --task bq001                       # one task (worker)

Every task is audited twice: under the benchmark's comparison (columns contained, NULL as zero,
absolute tolerance 1e-2, ``condition_cols`` as reference columns, ``ignore_order`` as the ordering)
and under isitright's strict default (positional columns, multisets, no NULL rule). Every finding is
emulated (DuckDB); nothing is confirmed natively until the BigQuery runbook has run. Each task runs
in its own process with a hard time limit, and a per-task cap on the search (wall time and 500
attempts, as in 0.5). Spider's gold result files are not read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CAP = 600.0
HARD_LIMIT_FACTOR = 4.0


def load_tasks() -> dict[str, dict]:
    tasks = {}
    for line in (HERE / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        tasks[record["id"]] = record
    return tasks


def load_gold_trust() -> dict[str, dict]:
    """``gold_trust.json`` (from ``gold_trust.py``, which reads the baseline run): per task whether
    the gold SQL reproduces one of Spider's result files on the real data. Absent means unknown."""
    path = HERE / "gold_trust.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def reference_column_variants(condition_cols: object) -> list[list[int] | None]:
    """Spider's ``condition_cols`` as a list of accepted column lists (``None``: all columns).

    [] means all columns; a list of ints is one list; a list of lists gives several, one per
    accepted gold result file, and Spider accepts a prediction that matches any of them (0.9: every
    variant is applied; 0.7 took the first only)."""
    if not condition_cols:
        return [None]
    if isinstance(condition_cols, int):
        return [[condition_cols]]
    assert isinstance(condition_cols, list)
    if isinstance(condition_cols[0], list):
        return [[int(c) for c in variant] or None for variant in condition_cols]
    return [[int(c) for c in condition_cols]]


def reference_columns(condition_cols: object) -> list[int] | None:
    """The first accepted column list (the 0.7 behaviour; kept for the owner-step scripts)."""
    return reference_column_variants(condition_cols)[0]


def benchmark_policy(variant: list[int] | None, ignore_order: bool) -> Any:
    """The benchmark's comparison for one accepted column list."""
    from isitright.packs.sql.models import ColumnComparisonPolicy, ComparisonPolicy, OrderingPolicy

    ordering = OrderingPolicy.UNORDERED if ignore_order else OrderingPolicy.ORDERED
    return ComparisonPolicy(
        columns=ColumnComparisonPolicy.CONTAINED,
        null_as_zero=True,
        float_absolute_tolerance=0.01,
        ordering=ordering,
        reference_columns=variant,
    ).model_copy(update={"effective_ordering": ordering})


def accepted_by(
    reference: dict, candidate: dict, variants: list[list[int] | None], ignore_order: bool
) -> list[int]:
    """Indexes of the variants under which the candidate's result matches the reference's. A
    benchmark finding is one that no variant accepts, as Spider scores with any of its files."""
    from isitright.packs.sql.comparison import ComparisonError, compare_results
    from isitright.packs.sql.models import QueryResult

    left, right = QueryResult.model_validate(reference), QueryResult.model_validate(candidate)
    out = []
    for index, variant in enumerate(variants):
        try:
            outcome = compare_results(
                left,
                right,
                policy=benchmark_policy(variant, ignore_order),
                reference_has_order_by=False,
            )
        except ComparisonError:
            continue  # a variant that does not fit the reference's columns accepts nothing
        if outcome.matches:
            out.append(index)
    return out


def audit_one(task_id: str, out: Path, cap: float, nested_scope: str = "path") -> dict:
    from isitright.packs.sql import (
        CheckConfig,
        SqlInputError,
        check,
        export_eval_cases,
        replay_report,
    )
    from isitright.packs.sql.constraints_file import load_constraint_schema
    from isitright.packs.sql.models import ColumnComparisonPolicy, OrderingPolicy

    record = load_tasks()[task_id]
    trust = load_gold_trust().get(task_id, {})
    ddl = (HERE / "ddl" / f"{task_id}.sql").read_text(encoding="utf-8")
    gold = (HERE / "gold" / f"{task_id}.sql").read_text(encoding="utf-8")
    candidate = (HERE / "candidate" / f"{task_id}.sql").read_text(encoding="utf-8")
    constraints_path = HERE / "constraints" / f"{task_id}.yaml"
    constraints = load_constraint_schema(constraints_path) if constraints_path.exists() else None
    ordering = OrderingPolicy.UNORDERED if record["ignore_order"] else OrderingPolicy.ORDERED
    variants = reference_column_variants(record["condition_cols"])
    labels = (
        ["benchmark"] if len(variants) == 1 else [f"benchmark[{i}]" for i in range(len(variants))]
    )
    settings = {
        label: CheckConfig(
            column_policy=ColumnComparisonPolicy.CONTAINED,
            null_as_zero=True,
            float_absolute_tolerance=0.01,
            ordering_policy=ordering,
            reference_columns=variant,
            wall_time_seconds=cap,
            nested_scope=nested_scope,
        )
        for label, variant in zip(labels, variants, strict=True)
    }
    settings["strict"] = CheckConfig(wall_time_seconds=cap, nested_scope=nested_scope)
    result: dict = {
        "id": task_id,
        "db": record["db"],
        "rewrites": len(record["rewrites"]),
        "constraints": constraints is not None,
        "gold_trusted": trust.get("trusted"),
        "settings": {
            "condition_cols": record["condition_cols"],
            "ignore_order": record["ignore_order"],
            "wall_time_cap_seconds": cap,
            "nested_scope": nested_scope,
        },
    }
    for label, config in settings.items():
        started = time.monotonic()
        entry: dict = {}
        try:
            report = check(
                reference_sql=gold,
                candidate_sql=candidate,
                dialect="bigquery",
                ddl=ddl,
                question=record["question"],
                case_id=task_id,
                constraints=constraints,
                config=config,
                gold_trusted=trust.get("trusted"),
                gold_trust_basis=trust.get("basis"),
            )
            entry["status"] = report.divergence_status.value
            entry["headline"] = report.headline
            entry["attempts"] = report.search.attempts
            entry["executed"] = report.search.executed
            entry["stopped_by"] = report.search.budget.get("stopped_by")
            entry["validity_tiers"] = report.validity.tiers
            entry["families_run"] = report.search.families_run
            entry["errors"] = [e.get("message", "")[:300] for e in report.errors][:3]
            entry["native_verification"] = report.extensions["sql"].get("native_verification")
            entry["rewrites"] = report.extensions["sql"].get("rewrites")
            if report.findings:
                finding = report.findings[0]
                state = finding.divergence["candidate_state"]
                rows = sum(len(v) for v in state.values())
                arrays = [
                    len(value)
                    for table in state.values()
                    for row in table
                    for value in row.values()
                    if isinstance(value, list)
                ]
                entry["finding"] = {
                    "families": [m.family for m in finding.mutation_path],
                    "mutation_path": [m.description for m in finding.mutation_path],
                    "minimized_rows": rows,
                    "tables": {k: len(v) for k, v in state.items() if v},
                    "longest_top_level_array": max(arrays, default=0),
                    "minimization": finding.minimization,
                    "validity": finding.validity.tiers,
                    "validity_notes": finding.validity.notes,
                    "difference": finding.divergence.get("difference"),
                    "kind": finding.divergence.get("kind"),
                    "reference_result_rows": len(finding.divergence["reference_result"]["rows"]),
                    "candidate_result_rows": len(finding.divergence["candidate_result"]["rows"]),
                    "found_on": finding.fidelity.found_on,
                    "verified_on": finding.fidelity.verified_on,
                }
                if label != "strict":
                    entry["finding"]["accepted_by_variants"] = accepted_by(
                        finding.divergence["reference_result"],
                        finding.divergence["candidate_result"],
                        variants,
                        record["ignore_order"],
                    )
                try:
                    entry["finding"]["replay_reproduced"] = replay_report(report)["reproduced"]
                    entry["finding"]["eval_cases_exported"] = len(export_eval_cases(report))
                except Exception as error:  # a replay problem is data, not a crash
                    entry["finding"]["replay_error"] = f"{type(error).__name__}: {error}"[:200]
                (out / f"{task_id}.{label}.report.json").write_text(
                    report.model_dump_json(indent=1), encoding="utf-8"
                )
        except SqlInputError as error:
            entry["status"] = "UNSUPPORTED"
            entry["unsupported"] = str(error)[:400]
        except Exception as error:
            entry["status"] = "ERROR"
            entry["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        entry["wall_seconds"] = round(time.monotonic() - started, 1)
        result[label] = entry
    if len(variants) > 1:
        result["benchmark"] = combine_variants([result[label] for label in labels])
    return result


def combine_variants(entries: list[dict]) -> dict:
    """The benchmark verdict of a task with several accepted column lists: a finding counts only if
    no accepted list takes the candidate's result on the finding's world (Spider accepts a
    prediction that matches any of its gold files). Each variant's own audit is kept beside it."""
    kept = [
        e["finding"]
        for e in entries
        if e.get("status") == "COUNTEREXAMPLE_FOUND" and not e["finding"]["accepted_by_variants"]
    ]
    statuses = [e.get("status") for e in entries]
    if kept:
        status = "COUNTEREXAMPLE_FOUND"
    elif "COUNTEREXAMPLE_FOUND" in statuses:
        status = "NOT_FOUND_WITHIN_BUDGET"  # every finding is accepted under another list
    elif all(s == statuses[0] for s in statuses):
        status = statuses[0]
    else:
        status = "INCONCLUSIVE"
    out: dict = {
        "status": status,
        "variants": len(entries),
        "variant_statuses": statuses,
        "findings_accepted_under_another_list": sum(
            1
            for e in entries
            if e.get("status") == "COUNTEREXAMPLE_FOUND" and e["finding"]["accepted_by_variants"]
        ),
    }
    if kept:
        out["finding"] = kept[0]
    return out


def _worker_command(out: Path, task_id: str, cap: float) -> list[str]:
    """Run the worker with the package from ISITRIGHT_SRC when set (a frozen copy of the code)."""
    src = os.environ.get("ISITRIGHT_SRC")
    args = [str(out), "--task", task_id, "--cap", str(cap)]
    if src is None:
        return ["-I", str(Path(__file__).resolve()), *args]
    code = (
        "import sys, runpy; "
        f"sys.path.insert(0, {src!r}); sys.argv = [{str(Path(__file__).resolve())!r}, *{args!r}]; "
        f"runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')"
    )
    return ["-c", code]


def run_all(out: Path, only: list[str] | None, cap: float) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    ids = [i for i in tasks if only is None or i in only]
    for task_id in ids:
        target = out / f"{task_id}.json"
        if target.exists():
            continue
        started = time.monotonic()
        try:
            done = subprocess.run(
                [sys.executable, *_worker_command(out, task_id, cap)],
                capture_output=True,
                text=True,
                timeout=cap * HARD_LIMIT_FACTOR,
                check=False,
            )
            if not target.exists():
                target.write_text(
                    json.dumps(
                        {
                            "id": task_id,
                            "worker_failed": True,
                            "returncode": done.returncode,
                            "stderr": done.stderr[-600:],
                        }
                    ),
                    encoding="utf-8",
                )
        except subprocess.TimeoutExpired:
            target.write_text(
                json.dumps({"id": task_id, "hard_timeout_seconds": cap * HARD_LIMIT_FACTOR}),
                encoding="utf-8",
            )
        print(task_id, round(time.monotonic() - started, 1), flush=True)


def main(argv: list[str]) -> None:
    out = Path(argv[0])
    cap = float(argv[argv.index("--cap") + 1]) if "--cap" in argv else DEFAULT_CAP
    # the workers inherit the scope through the environment
    scope = (
        argv[argv.index("--nested-scope") + 1]
        if "--nested-scope" in argv
        else os.environ.get("ISITRIGHT_DEMO_NESTED_SCOPE", "path")
    )
    os.environ["ISITRIGHT_DEMO_NESTED_SCOPE"] = scope
    if "--task" in argv:
        task_id = argv[argv.index("--task") + 1]
        out.mkdir(parents=True, exist_ok=True)
        result = audit_one(task_id, out, cap, scope)
        (out / f"{task_id}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        return
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    run_all(out, only, cap)


if __name__ == "__main__":
    main(sys.argv[1:])
