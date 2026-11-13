# Proposed fixture: pending owner review (written by Claude: the worlds of the clean cases, the
# expected outcomes, the mini demo files; the Spider gold and schemagate candidate SQL are theirs).
"""0.9 follow-ups of the Spider 2.0-lite demo: every ``condition_cols`` variant, Spider's result
files as the baseline reference where the gold SQL matches none, clean counterexamples for the
three findings the 0.7 review flagged, and the ``detected`` fixtures sent natively (on fakes)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.packs.sql.inline import assert_inline_only
from isitright.packs.sql.models import CanonicalValue, CanonicalValueKind, QueryResult, ResultColumn
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
from tests.test_bigquery_steps import Client, _mini_demo, runner, steps

DEMO = Path(__file__).parents[1] / "examples" / "sql" / "spider2"


def _load(name: str) -> Any:
    sys.path.insert(0, str(DEMO))
    spec = importlib.util.spec_from_file_location(name, DEMO / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_demo = _load("run_demo")
clean_cases = _load("clean_cases")


def result(names: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    def cell(value: Any) -> CanonicalValue:
        if value is None:
            return CanonicalValue(kind=CanonicalValueKind.NULL, value=None)
        if isinstance(value, float):
            return CanonicalValue(kind=CanonicalValueKind.FLOAT, value=value)
        if isinstance(value, int):
            return CanonicalValue(kind=CanonicalValueKind.INTEGER, value=value)
        return CanonicalValue(kind=CanonicalValueKind.TEXT, value=value)

    return QueryResult(
        columns=[ResultColumn(name=n) for n in names], rows=[[cell(v) for v in r] for r in rows]
    ).model_dump(mode="json")


# --- every condition_cols variant -------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition_cols", "variants"),
    [
        ([], [None]),
        (2, [[2]]),
        ([0, 1], [[0, 1]]),
        ([[0], [1]], [[0], [1]]),
        ([[0, 2], []], [[0, 2], None]),
    ],
)
def test_condition_cols_give_every_accepted_column_list(
    condition_cols: object, variants: list[list[int] | None]
) -> None:
    assert run_demo.reference_column_variants(condition_cols) == variants
    assert run_demo.reference_columns(condition_cols) == variants[0]  # the 0.7 reading


def test_a_finding_one_list_rejects_and_another_accepts_is_not_a_benchmark_finding() -> None:
    gold = result(["name", "total"], [["a", 1], ["b", 2]])
    candidate = result(["name", "total"], [["a", 1], ["b", 3]])  # names agree, totals do not
    assert run_demo.accepted_by(gold, candidate, [[1], [0]], True) == [1]
    assert run_demo.accepted_by(gold, candidate, [[1]], True) == []
    # a list that does not fit the reference's columns accepts nothing; it is not an error
    assert run_demo.accepted_by(gold, candidate, [[5]], True) == []


def test_variants_combine_into_one_benchmark_verdict() -> None:
    accepted = {"status": "COUNTEREXAMPLE_FOUND", "finding": {"accepted_by_variants": [1]}}
    rejected = {"status": "COUNTEREXAMPLE_FOUND", "finding": {"accepted_by_variants": []}}
    none = {"status": "NOT_FOUND_WITHIN_BUDGET"}
    combined = run_demo.combine_variants([accepted, none])
    assert combined["status"] == "NOT_FOUND_WITHIN_BUDGET"
    assert combined["findings_accepted_under_another_list"] == 1 and "finding" not in combined
    combined = run_demo.combine_variants([none, rejected])
    assert (
        combined["status"] == "COUNTEREXAMPLE_FOUND" and combined["finding"] is rejected["finding"]
    )
    assert run_demo.combine_variants([none, none])["status"] == "NOT_FOUND_WITHIN_BUDGET"
    unsupported = {"status": "UNSUPPORTED"}
    assert run_demo.combine_variants([unsupported, unsupported])["status"] == "UNSUPPORTED"


# --- the baseline: Spider's files are the reference where the gold SQL matches none -------------


def _baseline(tmp_path: Path, files: dict[str, str], respond: Any) -> dict[str, Any]:
    demo = _mini_demo(tmp_path)
    gold_dir = tmp_path / "spider2" / "spider2-lite" / "evaluation_suite" / "gold" / "exec_result"
    for name, text in files.items():
        (gold_dir / name).write_text(text, encoding="utf-8")
    return steps.baseline(runner(Client(respond=respond)), tmp_path / "spider2", demo=demo)


def _gold_left_candidate_cross(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    return ["id", "tag"], ([(1, 5), (2, None)] if "LEFT" in sql else [(1, 5)])


def test_an_untrusted_gold_is_replaced_by_the_file_the_candidate_matches(tmp_path: Path) -> None:
    out = _baseline(tmp_path, {"t1_a.csv": "id,tag\n1,5\n"}, _gold_left_candidate_cross)
    entry = out["tasks"][0]
    assert entry["gold_trusted"] is False  # the gold SQL returns a row the file does not have
    assert entry["pair_matches_under_task_settings"] is False  # gold SQL against the candidate
    assert entry["candidate_matches_spider_files"] == ["t1_a.csv"]
    assert entry["baseline_reference"].startswith("Spider's result files")
    assert entry["baseline_agrees"] is True and out["kept_pairs"] == ["t1"]
    assert out["kept_with_gold_sql_as_reference"] == 0


def test_a_trusted_gold_stays_the_reference_even_if_the_candidate_matches_a_file(
    tmp_path: Path,
) -> None:
    out = _baseline(
        tmp_path,
        {"t1_a.csv": "id,tag\n1,5\n2,\n", "t1_b.csv": "id,tag\n1,5\n"},
        _gold_left_candidate_cross,
    )
    entry = out["tasks"][0]
    assert entry["gold_trusted"] is True and entry["baseline_reference"] == "the gold SQL"
    assert entry["candidate_matches_spider_files"] == ["t1_b.csv"]
    assert entry["baseline_agrees"] is False and out["kept_pairs"] == []


def test_without_any_file_the_gold_sql_is_the_reference_and_says_it_is_unchecked(
    tmp_path: Path,
) -> None:
    out = _baseline(tmp_path, {}, lambda sql: (["id", "tag"], [(1, 5)]))
    entry = out["tasks"][0]
    assert entry["gold_trusted"] is None
    assert entry["baseline_reference"] == "the gold SQL (no Spider result file to check it)"
    assert entry["baseline_agrees"] is True


# --- clean counterexamples ----------------------------------------------------------------------


def test_bq402_clean_world_differs_on_the_average_per_purchaser() -> None:
    case = clean_cases.run_case("bq402", clean_cases.WORLDS["bq402"])
    assert case["gold"]["rows"] == [[0.5, 1.0]] and case["candidate"]["rows"] == [[0.5, 2.0]]
    assert case["verdicts"]["benchmark all columns"].startswith(
        "reference column avg_transactions_per_purchaser"
    )
    assert case["verdicts"]["strict"] != "match"


def test_bq402_with_one_visitor_only_is_accepted_by_the_benchmark_comparison() -> None:
    """Why the clean world needs a second visitor: the benchmark pairs columns by value."""
    one = {
        "rows": {"web_analytics": clean_cases.WORLDS["bq402"]["rows"]["web_analytics"][:2]},
        "question": "",
        "reading": "",
    }
    case = clean_cases.run_case("bq402", one)
    assert case["gold"]["rows"] == [[1.0, 1.0]] and case["candidate"]["rows"] == [[1.0, 2.0]]
    assert case["verdicts"]["benchmark all columns"] == "match"


def test_bq025_tables_that_agree_leave_only_the_rounding() -> None:
    case = clean_cases.run_case("bq025", clean_cases.WORLDS["bq025"])
    gold, candidate = case["gold"]["rows"], case["candidate"]["rows"]
    assert gold[0][:3] == candidate[0][:3] == ["Aland", 100, 300]
    assert gold[0][3] == 33.33 and abs(candidate[0][3] - 100 / 3) < 1e-9
    assert case["verdicts"]["benchmark [0, 1, 2, 3]"] == "match"
    assert case["verdicts"]["strict"] != "match"


def test_bq398_the_gold_returns_one_indicator_twice() -> None:
    case = clean_cases.run_case("bq398", clean_cases.WORLDS["bq398"])
    assert [r[0] for r in case["gold"]["rows"]].count("Indicator A") == 2
    assert [r[0] for r in case["candidate"]["rows"]] == [
        "Indicator A",
        "Indicator B",
        "Indicator C",
    ]
    assert case["verdicts"]["benchmark [0]"] != "match"
    assert case["verdicts"]["benchmark [1]"].startswith("not applicable")


@pytest.mark.parametrize("task_id", sorted(clean_cases.WORLDS))
def test_each_clean_world_has_inline_text_that_names_no_real_table(task_id: str) -> None:
    from isitright.packs.sql.dialects import get_dialect

    case = clean_cases.run_case(task_id, clean_cases.WORLDS[task_id])
    for text in case["inline"].values():
        assert_inline_only(text, get_dialect("bigquery"))


# --- the detected fixtures, sent natively (here: a fake host) ----------------------------------


def test_the_detected_fixtures_are_sent_inline_except_the_one_that_needs_real_tables() -> None:
    sent: list[str] = []

    class Host:
        records: list[dict[str, Any]] = []  # noqa: RUF012

        def run_inline(self, sql: str, dialect: Any, **kwargs: Any) -> QueryResult:
            assert_inline_only(sql, dialect)
            sent.append(sql)
            if "ST_GEOGPOINT" in sql:
                raise QueryExecutionError("simulated: geography values are not comparable here")
            return QueryResult.model_validate(result(["a"], [["[1, 2]"]]))

    report = steps.smoke_detected(Host())
    by_id = {row["id"]: row for row in report["fixtures"]}
    assert set(by_id) == {"bq-array-agg-limit", "bq-wildcard-table", "bq-geography"}
    assert by_id["bq-wildcard-table"]["outcome"] == "not sent"
    assert "wildcard table" in by_id["bq-wildcard-table"]["reason"]
    assert by_id["bq-array-agg-limit"]["observed_native"] == [["[1, 2]"]]
    assert by_id["bq-geography"]["observed_native"] == "ERROR"
    assert len(sent) == 2 and all("`d.t`" not in s and " d.t" not in s for s in sent)
    assert report["counts"] == {"observed": 2, "not sent": 1}
