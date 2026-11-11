# Proposed fixture: pending owner review (constructed mini demo directory; fakes, not BigQuery).
"""The owner's BigQuery steps, against fakes. They have not run on BigQuery: a fake cannot test
BigQuery's semantics, only that the steps send what the runbook says, within the caps."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.packs.sql import ConnectionHost
from isitright.packs.sql.inline import assert_inline_only

SCRIPT = Path(__file__).parents[1] / "examples" / "sql" / "spider2" / "bigquery_steps.py"
spec = importlib.util.spec_from_file_location("bigquery_steps", SCRIPT)
assert spec is not None and spec.loader is not None
steps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(steps)


class Job:
    def __init__(self, estimate: int = 0, rows: Any = (), names: Any = ()) -> None:
        self.total_bytes_processed = estimate
        self.total_bytes_billed = estimate
        self.schema = [SimpleNamespace(name=n) for n in names]
        self._rows = list(rows)

    def result(self, timeout: Any = None) -> list[Any]:
        return self._rows


class Client:
    def __init__(self, respond: Any = None, estimate: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.respond = respond or (lambda sql: ([], []))
        self.estimate = estimate

    def query(self, sql: str, job_config: dict[str, Any]) -> Job:
        self.calls.append((sql, job_config))
        if job_config.get("dry_run"):
            return Job(estimate=self.estimate)
        names, rows = self.respond(sql)
        return Job(estimate=self.estimate, rows=rows, names=names)


def runner(client: Client, per: int = 1000, total: int = 5000) -> Any:
    return steps.Runner(
        client, config=lambda **kw: kw, max_bytes_per_query=per, max_bytes_total=total
    )


def test_every_query_is_dry_run_first_and_capped() -> None:
    client = Client(estimate=300)
    r = runner(client)
    r.run("SELECT 1")
    (dry_sql, dry), (run_sql, run) = client.calls
    assert dry["dry_run"] is True and run["maximum_bytes_billed"] == 1000
    assert dry_sql == run_sql and run["labels"]["isitright_phase"] == "runbook"
    assert r.summary()["estimated_bytes"] == 300 and r.summary()["queries"] == 1


def test_a_query_over_the_cap_is_never_run_and_the_total_is_enforced() -> None:
    client = Client(estimate=2000)
    with pytest.raises(steps.CapExceeded, match="per-query"):
        runner(client).run("SELECT 1")
    assert len(client.calls) == 1  # only the dry run
    client = Client(estimate=900)
    r = runner(client, per=1000, total=2000)
    r.run("SELECT 1")
    r.run("SELECT 2")
    with pytest.raises(steps.CapExceeded, match="total"):
        r.run("SELECT 3")


def _mini_demo(tmp_path: Path) -> Path:
    demo = tmp_path / "demo"
    (tmp_path / "spider2" / "spider2-lite" / "evaluation_suite" / "gold" / "exec_result").mkdir(
        parents=True
    )
    for sub in ("ddl", "gold", "candidate", "original/gold", "original/candidate"):
        (demo / sub).mkdir(parents=True)
    ddl = "CREATE TABLE `proj.shop.items` (id INT64 NOT NULL, tags ARRAY<INT64>)"
    left = "SELECT t.id, tag FROM `proj.shop.items` AS t LEFT JOIN UNNEST(t.tags) AS tag"
    cross = "SELECT t.id, tag FROM `proj.shop.items` AS t CROSS JOIN UNNEST(t.tags) AS tag"
    (demo / "ddl" / "t1.sql").write_text(ddl, encoding="utf-8")
    for side, sql in (("gold", left), ("candidate", cross)):
        (demo / side / "t1.sql").write_text(sql, encoding="utf-8")
        (demo / "original" / side / "t1.sql").write_text(sql, encoding="utf-8")
    task = {
        "id": "t1",
        "db": "d",
        "question": "which items have tags?",
        "condition_cols": [],
        "ignore_order": True,
        "rewrites": [],
        "tables": ["proj.shop.items"],
    }
    (demo / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
    return demo


def test_schema_check_reports_columns_that_changed_since_the_snapshot(tmp_path: Path) -> None:
    def respond(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        assert "INFORMATION_SCHEMA.COLUMNS" in sql and "table_name = 'items'" in sql
        return ["column_name", "data_type"], [("id", "INT64"), ("brand_new", "STRING")]

    result = steps.schema_check(runner(Client(respond=respond)), demo=_mini_demo(tmp_path))
    (difference,) = result["differences"]
    assert difference["columns_missing_live"] == ["tags"]
    assert difference["columns_new_live"] == ["brand_new"]
    assert result["tables_checked"] == 1


def test_baseline_keeps_pairs_that_match_under_the_task_settings(tmp_path: Path) -> None:
    demo = _mini_demo(tmp_path)
    same = Client(respond=lambda sql: (["id", "tag"], [(1, 5), (2, None)]))
    result = steps.baseline(runner(same), tmp_path / "spider2", demo=demo)
    assert result["kept_pairs"] == ["t1"] and len(same.calls) == 4  # two queries, dry run each

    def differ(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return ["id", "tag"], ([(1, 5), (2, None)] if "LEFT" in sql else [(1, 5)])

    result = steps.baseline(runner(Client(respond=differ)), tmp_path / "spider2", demo=demo)
    assert (
        result["kept_pairs"] == []
        and result["tasks"][0]["pair_matches_under_task_settings"] is False
    )


class _Iterator(list):  # what job.result() returns: the rows, with the result schema
    def __init__(self, rows: Any, names: Any) -> None:
        super().__init__(rows)
        self.schema = [SimpleNamespace(name=n) for n in names]


class _LateSchemaClient(Client):
    """A job whose own `schema` is empty after `result()`, as the real client can leave it."""

    def query(self, sql: str, job_config: dict[str, Any]) -> Job:
        job = super().query(sql, job_config)
        if not job_config.get("dry_run"):
            names, rows = self.respond(sql)
            job.schema = []
            job.result = lambda timeout=None, rows=rows, names=names: _Iterator(rows, names)  # type: ignore[method-assign]
        return job


def test_the_column_names_come_from_the_row_iterator_when_the_job_has_none() -> None:
    client = _LateSchemaClient(respond=lambda sql: (["id", "tag"], [(1, 5)]))
    names, rows = runner(client).run("SELECT 1")
    assert names == ["id", "tag"] and rows == [(1, 5)]


def test_baseline_records_a_comparison_error_and_goes_on(tmp_path: Path) -> None:
    demo = _mini_demo(tmp_path)
    task = json.loads((demo / "tasks.jsonl").read_text(encoding="utf-8"))
    task["condition_cols"] = [[7]]  # a column the result does not have
    second = dict(task, id="t2", condition_cols=[])
    for side in ("gold", "candidate"):
        text = (demo / "original" / side / "t1.sql").read_text(encoding="utf-8")
        (demo / "original" / side / "t2.sql").write_text(text, encoding="utf-8")
    lines = [json.dumps(task), json.dumps(second)]
    (demo / "tasks.jsonl").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    same = Client(respond=lambda sql: (["id", "tag"], [(1, 5)]))
    result = steps.baseline(runner(same), tmp_path / "spider2", demo=demo)
    first, other = result["tasks"]
    assert first["error"] == "no condition_cols list fits the gold's 2 columns"
    assert other["pair_matches_under_task_settings"] is True and result["kept_pairs"] == ["t2"]


def test_baseline_tries_each_condition_cols_variant_that_fits(tmp_path: Path) -> None:
    demo = _mini_demo(tmp_path)
    task = json.loads((demo / "tasks.jsonl").read_text(encoding="utf-8"))
    task["condition_cols"] = [[5], [1]]  # the first list does not fit; the second does
    (demo / "tasks.jsonl").write_text(json.dumps(task) + chr(10), encoding="utf-8")
    same = Client(respond=lambda sql: (["id", "tag"], [(1, 5)]))
    result = steps.baseline(runner(same), tmp_path / "spider2", demo=demo)
    entry = result["tasks"][0]
    assert entry["condition_cols_lists_fitting"] == "1 of 2"
    assert entry["matched_condition_cols"] == [1] and result["kept_pairs"] == ["t1"]


def test_baseline_refuses_to_start_without_the_spider_gold_results(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Spider2 checkout"):
        steps.baseline(runner(Client()), tmp_path / "missing", demo=_mini_demo(tmp_path))


def test_confirm_refuses_an_empty_results_directory(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    with pytest.raises(SystemExit, match="no task records"):
        steps.confirm(
            ConnectionHost(run=lambda sql: ([], [])),
            tmp_path / "results",
            demo=_mini_demo(tmp_path),
        )


def test_the_rewrite_family_table_is_outside_the_wildcard_prefix() -> None:
    statements: list[str] = []

    def respond(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        statements.append(sql)
        return (["id", "s", "suffix"], [(1, "a", "x")]) if sql.startswith("SELECT") else ([], [])

    steps.rewrite_equivalence(runner(Client(respond=respond)), "proj", "scratch")
    wildcard = next(s for s in statements if s.endswith("*`"))
    prefix = wildcard.split("scratch.")[1].rstrip("*`")
    family = next(s for s in statements if "AS _shard" in s or "UNION ALL" in s)
    family_name = family.split("`proj.scratch.")[1].split("`")[0]
    assert not family_name.startswith(prefix)


def test_baseline_does_not_compare_a_result_without_column_names(tmp_path: Path) -> None:
    result = steps.baseline(
        runner(Client(respond=lambda sql: ([], [(1,)]))),
        tmp_path / "spider2",
        demo=_mini_demo(tmp_path),
    )
    assert "no column names" in result["tasks"][0]["error"] and result["kept"] == 0


def test_the_query_cache_is_off_unless_the_runner_asks_for_it() -> None:
    off, on = Client(), Client()
    runner(off).run("SELECT 1")
    steps.Runner(
        on,
        config=lambda **kw: kw,
        max_bytes_per_query=1000,
        max_bytes_total=5000,
        use_query_cache=True,
    ).run("SELECT 1")
    assert off.calls[1][1]["use_query_cache"] is False
    assert on.calls[1][1]["use_query_cache"] is True


def test_baseline_skips_a_task_whose_estimate_is_over_the_cap(tmp_path: Path) -> None:
    result = steps.baseline(
        runner(Client(estimate=10**6), per=1000), tmp_path / "spider2", demo=_mini_demo(tmp_path)
    )
    assert "skipped" in result["tasks"][0] and result["kept"] == 0


def test_the_rewrite_check_drops_its_tables_even_when_a_query_fails() -> None:
    statements: list[str] = []

    def respond(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        statements.append(sql)
        if sql.startswith("SELECT"):
            raise RuntimeError("boom")
        return [], []

    with pytest.raises(RuntimeError):
        steps.rewrite_equivalence(runner(Client(respond=respond)), "proj", "scratch")
    created = [s for s in statements if s.startswith("CREATE TABLE")]
    dropped = [s for s in statements if s.startswith("DROP TABLE")]
    assert len(created) == 4 and len(dropped) == 4  # three shards and the family table
    assert all("`proj.scratch." in s for s in created + dropped)


def test_the_rewrite_check_compares_the_wildcard_with_the_rewrite() -> None:
    def respond(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return (["id", "s", "suffix"], [(1, "a", "x")]) if sql.startswith("SELECT") else ([], [])

    result = steps.rewrite_equivalence(runner(Client(respond=respond)), "proj", "scratch")
    assert result["all_equal"] is True and len(result["checks"]) == 2


def test_confirm_reruns_tasks_with_a_finding_on_the_given_host(tmp_path: Path) -> None:
    demo = _mini_demo(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    (results / "t1.json").write_text(
        json.dumps(
            {
                "id": "t1",
                "settings": {"wall_time_cap_seconds": 60},
                "benchmark": {"status": "COUNTEREXAMPLE_FOUND"},
                "strict": {"status": "NOT_FOUND_WITHIN_BUDGET"},
            }
        ),
        encoding="utf-8",
    )
    seen: list[str] = []

    def run(sql: str) -> tuple[list[str], list[list[Any]]]:
        assert_inline_only(sql, steps_dialect())
        seen.append(sql)
        return ["id", "tag"], ([[10, None]] if "LEFT JOIN" in sql else [])

    result = steps.confirm(ConnectionHost(run=run), results, demo=demo)
    assert result["total"] == 1 and result["verified"] == 1
    assert result["confirmations"][0]["verified_on"] == "NATIVE_INLINE" and seen


def steps_dialect() -> Any:
    from isitright.packs.sql.dialects import get_dialect

    return get_dialect("bigquery")


def test_the_smoke_step_compares_every_bigquery_fixture_with_its_documented_outcome() -> None:
    from tests.warehouse_fixtures import FIXTURES

    wanted = [f for f in FIXTURES if f.dialect == "bigquery" and f.status != "detected"]
    answers = iter(wanted)

    class Host:
        records: list[dict[str, Any]] = []  # noqa: RUF012

        def run_inline(self, sql: str, dialect: Any, **kwargs: Any) -> Any:
            assert_inline_only(sql, dialect)
            fixture = next(answers)
            if fixture.native == "ERROR":
                from isitright.packs.sql.sqlite_sandbox import QueryExecutionError

                raise QueryExecutionError(f"simulated native error: {fixture.native_error}")
            from isitright.packs.sql.models import (
                CanonicalValue,
                CanonicalValueKind,
                QueryResult,
                ResultColumn,
            )

            rows = fixture.native if fixture.native is not None else fixture.emulated
            cells = [
                [CanonicalValue(kind=CanonicalValueKind.JSON, value=v) for v in row] for row in rows
            ]
            width = len(cells[0]) if cells else 0
            return QueryResult(
                columns=[ResultColumn(name=f"c{i}") for i in range(width)], rows=cells
            )

    report = steps.smoke(Host())
    assert len(report["fixtures"]) == len(wanted)
    assert report["counts"].get("DIFFERS", 0) == 0
    assert report["counts"]["confirmed"] == sum(1 for f in wanted if f.native is not None)


def test_a_dry_run_only_baseline_prints_estimates_and_reads_nothing(tmp_path: Path) -> None:
    client = Client(estimate=700)
    r = steps.Runner(
        client,
        config=lambda **kw: kw,
        max_bytes_per_query=1000,
        max_bytes_total=10_000,
        dry_run_only=True,
    )
    result = steps.baseline(r, tmp_path / "spider2", demo=_mini_demo(tmp_path))
    assert all(call[1].get("dry_run") for call in client.calls)
    assert result["tasks"][0]["gold_estimate"] == 700
    assert result["tasks"][0]["candidate_estimate"] == 700
    assert result["estimated_bytes"] == 1400 and result["billed_bytes"] == 0


def test_schema_check_records_a_dataset_it_cannot_read_and_goes_on(tmp_path: Path) -> None:
    def denied(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        raise PermissionError("Access Denied: dataset shop")

    result = steps.schema_check(runner(Client(respond=denied)), demo=_mini_demo(tmp_path))
    assert "Access Denied" in result["differences"][0]["error"]


def test_baseline_compares_a_numeric_gold_column_with_a_float_candidate_column(
    tmp_path: Path,
) -> None:
    """BigQuery returns NUMERIC as Decimal; read as text it never matched a FLOAT64 column."""
    from decimal import Decimal

    def respond(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return ["avg"], [(Decimal("2.50"),)] if "LEFT" in sql else [(2.5,)]

    result = steps.baseline(
        runner(Client(respond=respond)), tmp_path / "spider2", demo=_mini_demo(tmp_path)
    )
    assert result["kept_pairs"] == ["t1"]


def test_baseline_shows_samples_of_a_pair_that_does_not_match(tmp_path: Path) -> None:
    demo = _mini_demo(tmp_path)
    gold_dir = tmp_path / "spider2" / "spider2-lite" / "evaluation_suite" / "gold" / "exec_result"
    (gold_dir / "t1_a.csv").write_text("id,tag\n1,5\n2,\n", encoding="utf-8")

    def differ(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return ["id", "tag"], ([(1, 5), (2, None)] if "LEFT" in sql else [(1, 5)])

    entry = steps.baseline(runner(Client(respond=differ)), tmp_path / "spider2", demo=demo)[
        "tasks"
    ][0]
    assert entry["pair_matches_under_task_settings"] is False
    assert entry["candidate_sample"]["rows"] == [["int:1", "int:5"]]
    assert entry["spider_gold_row_counts"] == [2]
    assert entry["gold_row_count_equals_spider_gold_csv"] is True
    assert entry["spider_gold_csv_samples"] == [[["id", "tag"], ["1", "5"], ["2", ""]]]


def _baseline_entry(tmp_path: Path, files: dict[str, str]) -> dict[str, Any]:
    demo = _mini_demo(tmp_path)
    gold_dir = tmp_path / "spider2" / "spider2-lite" / "evaluation_suite" / "gold" / "exec_result"
    for name, text in files.items():
        (gold_dir / name).write_text(text, encoding="utf-8")
    same = Client(respond=lambda sql: (["id", "tag"], [(1, 5), (2, None)]))
    return steps.baseline(runner(same), tmp_path / "spider2", demo=demo)["tasks"][0]


def test_gold_is_trusted_only_when_it_reproduces_one_of_spiders_result_files(
    tmp_path: Path,
) -> None:
    entry = _baseline_entry(
        tmp_path, {"t1_a.csv": "id,tag\n9,9\n", "t1_b.csv": "ID,TAG\n2,\n1,5.0\n"}
    )
    assert entry["gold_trusted"] is True
    assert entry["gold_matches_spider_files"] == ["t1_b.csv"]  # row order, case and 5 against 5.0
    assert "t1_b.csv" in entry["gold_trust_basis"]


def test_gold_that_matches_no_result_file_is_not_trusted_and_says_why(tmp_path: Path) -> None:
    entry = _baseline_entry(tmp_path, {"t1_a.csv": "id,tag\n1,6\n2,\n"})
    assert entry["gold_trusted"] is False and entry["gold_matches_spider_files"] == []
    assert "equals none of Spider's 1 result files" in entry["gold_trust_basis"]


def test_gold_trust_is_unknown_without_a_result_file_and_the_script_skips_it(
    tmp_path: Path,
) -> None:
    entry = _baseline_entry(tmp_path, {})
    assert entry["gold_trusted"] is None
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gold_trust", Path(steps.__file__).with_name("gold_trust.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = tmp_path / "baseline.json"
    trusted = {"id": "a", "gold_trusted": True, "gold_trust_basis": "x"}
    baseline.write_text(json.dumps({"tasks": [entry, trusted]}), encoding="utf-8")
    target = tmp_path / "gold_trust.json"
    assert module.main([str(baseline), str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": {"trusted": True, "basis": "x"}}
