# Proposed fixture: pending owner review.
# Written by Claude: the three worlds below and the reading of each. The gold and candidate SQL are
# Spider's and schemagate's, unchanged (the copies in gold/ and candidate/).
"""Clean counterexamples for the three Spider findings the 0.7 review flagged (bq402, bq025, bq398).

The search's minimized worlds for these tasks were valid by the rules declared, but hard to read
(a NULL visitor id, a table filled while the gold's tables are empty, a row whose name and code
disagree). Each world here is written by hand to answer the question the review asked of that task,
with every row consistent with the column descriptions in Spider's DDL:

* bq402: one visitor with two sessions, one transaction in each. Does the gold's average per row
  differ from an average per purchaser? (review: "gold 1, candidate 2")
* bq025: one country, the same in all three census tables, under-20 population a third of the
  total. Do the queries still differ once the tables agree with each other?
* bq398: Russia with a region, one indicator reported in two years. Does the gold return the same
  indicator twice?

Both queries run on DuckDB, as in the demo (``EMULATED``), under the benchmark's comparison and the
strict default. The inline BigQuery text of each query is written beside the cases so the owner can
confirm the outcome on BigQuery (the runbook's confirmation step); nothing here was run natively.

    python examples/sql/spider2/clean_cases.py OUT_DIR

writes ``OUT_DIR/clean-cases.md`` (question, world, both outputs and the verdicts side by side),
``OUT_DIR/clean-cases.json`` and ``OUT_DIR/inline/<task>-{gold,candidate}.sql``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

WORLDS: dict[str, dict[str, Any]] = {
    "bq402": {
        "question": "the average number of transactions per purchaser",
        "rows": {
            "web_analytics": [
                {"fullVisitorId": "v1", "visitId": 1, "totals": {"transactions": 1}},
                {"fullVisitorId": "v1", "visitId": 2, "totals": {"transactions": 1}},
                {"fullVisitorId": "v2", "visitId": 3, "totals": {"transactions": None}},
            ]
        },
        "reading": "One purchaser (v1) with two transactions in two sessions, and a visitor (v2) "
        "who bought nothing. The question defines the average per purchaser (2); the gold "
        "averages per row with a transaction (1). The second visitor is needed: with v1 alone the "
        "conversion rate is 1.0, and the benchmark's comparison, which matches each gold column "
        "with any candidate column, pairs the gold's average (1.0) with the candidate's "
        "conversion rate and accepts the candidate.",
    },
    "bq025": {
        "question": "the share of the population under 20, when the three tables agree",
        "rows": {
            "midyear_population": [
                {
                    "country_code": "AA",
                    "country_name": "Aland",
                    "year": 2020,
                    "midyear_population": 300,
                },
            ],
            "midyear_population_agespecific": [
                {
                    "country_code": "AA",
                    "country_name": "Aland",
                    "year": 2020,
                    "sex": "Both",
                    "age": age,
                    "population": 5,
                }
                for age in range(20)
            ],
            "midyear_population_5yr_age_sex": [
                {
                    "country_code": "AA",
                    "country_name": "Aland",
                    "year": 2020,
                    "total_flag": "A",
                    "starting_age": start,
                    "age_group_indicator": "-",
                    "ending_age": start + 4,
                    "midyear_population": 25,
                }
                for start in (0, 5, 10, 15)
            ]
            + [
                {
                    "country_code": "AA",
                    "country_name": "Aland",
                    "year": 2020,
                    "total_flag": "A",
                    "starting_age": 20,
                    "age_group_indicator": "+",
                    "ending_age": 0,
                    "midyear_population": 200,
                },
                {
                    "country_code": "AA",
                    "country_name": "Aland",
                    "year": 2020,
                    "total_flag": "*",
                    "starting_age": 0,
                    "age_group_indicator": "+",
                    "ending_age": 0,
                    "midyear_population": 300,
                },
            ],
        },
        "reading": "The tables agree: 100 of 300 are under 20. Both queries count 100 of 300; "
        "the gold rounds the percentage to two places, the candidate does not.",
    },
    "bq398": {
        "question": "the top three debt indicators for Russia",
        "rows": {
            "country_summary": [
                {"country_code": "RUS", "short_name": "Russia", "region": "Europe & Central Asia"},
            ],
            "international_debt": [
                {
                    "country_name": "Russian Federation",
                    "country_code": "RUS",
                    "indicator_name": "Indicator A",
                    "indicator_code": "A",
                    "value": 7.0,
                    "year": 2019,
                },
                {
                    "country_name": "Russian Federation",
                    "country_code": "RUS",
                    "indicator_name": "Indicator A",
                    "indicator_code": "A",
                    "value": 5.0,
                    "year": 2018,
                },
                {
                    "country_name": "Russian Federation",
                    "country_code": "RUS",
                    "indicator_name": "Indicator B",
                    "indicator_code": "B",
                    "value": 3.0,
                    "year": 2019,
                },
                {
                    "country_name": "Russian Federation",
                    "country_code": "RUS",
                    "indicator_name": "Indicator C",
                    "indicator_code": "C",
                    "value": 1.0,
                    "year": 2019,
                },
            ],
        },
        "reading": "Indicator A is reported in two years. The gold keeps distinct (value, "
        "indicator) rows, so A can fill two of its three places; the candidate takes each "
        "indicator's maximum. The gold also applies LIMIT 3 outside the ordered CTE with no "
        "outer ORDER BY, so which three rows it returns is not guaranteed.",
    },
}


def run_case(task_id: str, world: dict[str, Any]) -> dict[str, Any]:
    from isitright.packs.sql.comparison import ComparisonError, compare_results
    from isitright.packs.sql.dialects import get_dialect
    from isitright.packs.sql.hosts import DuckdbHost
    from isitright.packs.sql.inline import inline_sql
    from isitright.packs.sql.mapping import build_model
    from isitright.packs.sql.models import (
        ColumnComparisonPolicy,
        ComparisonPolicy,
        OrderingPolicy,
    )
    from isitright.packs.sql.postgres_ddl import Schema
    from isitright.packs.sql.replaying import _state
    from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema
    from isitright.packs.sql.warehouse_sql import parse_query, resolve_tables, to_duckdb

    sys.path.insert(0, str(HERE))
    from run_demo import load_tasks, reference_column_variants

    record = load_tasks()[task_id]
    dialect = get_dialect("bigquery")
    db = parse_warehouse_schema(
        (HERE / "ddl" / f"{task_id}.sql").read_text(encoding="utf-8"), dialect
    )
    state = _state(build_model(db, "bigquery"), world["rows"])
    texts = {
        side: (HERE / side / f"{task_id}.sql").read_text(encoding="utf-8")
        for side in ("gold", "candidate")
    }
    trees = {side: resolve_tables(parse_query(text, dialect), db) for side, text in texts.items()}
    host = DuckdbHost(Schema(db), dialect)
    left, right = host.run_pair(
        state,
        to_duckdb(trees["gold"], dialect, db).sql,
        to_duckdb(trees["candidate"], dialect, db).sql,
        timeout_seconds=60,
        max_result_rows=100,
    )
    ordering = OrderingPolicy.UNORDERED if record["ignore_order"] else OrderingPolicy.ORDERED
    verdicts: dict[str, Any] = {}
    for variant in reference_column_variants(record["condition_cols"]) or [None]:
        policy = ComparisonPolicy(
            columns=ColumnComparisonPolicy.CONTAINED,
            null_as_zero=True,
            float_absolute_tolerance=0.01,
            ordering=ordering,
            reference_columns=variant,
        ).model_copy(update={"effective_ordering": ordering})
        name = f"benchmark {variant or 'all columns'}"
        try:
            outcome = compare_results(left, right, policy=policy, reference_has_order_by=False)
        except ComparisonError as error:  # a list that belongs to another gold file
            verdicts[name] = f"not applicable: {error}"
            continue
        verdicts[name] = outcome.difference or "match"
    strict = compare_results(left, right, policy=ComparisonPolicy(), reference_has_order_by=False)
    verdicts["strict"] = strict.difference or "match"
    inline = {side: inline_sql(tree, dialect, db, state) for side, tree in trees.items()}
    return {
        "task": task_id,
        "question": record["question"],
        "asks": world["question"],
        "rows": world["rows"],
        "gold": {
            "columns": [c.name for c in left.columns],
            "rows": [[c.value for c in r] for r in left.rows],
        },
        "candidate": {
            "columns": [c.name for c in right.columns],
            "rows": [[c.value for c in r] for r in right.rows],
        },
        "verdicts": verdicts,
        "reading": world["reading"],
        "inline": inline,
        "found_on": "EMULATED (DuckDB); not confirmed on BigQuery",
    }


def _table(result: dict[str, Any]) -> str:
    lines = ["| " + " | ".join(result["columns"]) + " |", "|" + "---|" * len(result["columns"])]
    lines += [
        "| " + " | ".join("NULL" if v is None else str(v) for v in row) + " |"
        for row in result["rows"]
    ]
    return "\n".join(lines) if result["rows"] else "\n".join(lines[:2]) + "\n(no rows)"


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    (out / "inline").mkdir(parents=True, exist_ok=True)
    cases = [run_case(task_id, world) for task_id, world in WORLDS.items()]
    md = [
        "# Clean counterexamples (bq402, bq025, bq398)",
        "",
        "Worlds written by hand (Claude); queries by Spider (gold) and schemagate (candidate). "
        "Run on DuckDB, not on BigQuery.",
        "",
    ]
    for case in cases:
        md += [
            f"## {case['task']}",
            "",
            f"**Question.** {case['question']}",
            "",
            f"**This world asks:** {case['asks']}.",
            "",
            "**World:**",
            "",
            "```json",
            json.dumps(case["rows"], indent=1),
            "```",
            "",
            "**Gold:**",
            "",
            _table(case["gold"]),
            "",
            "**Candidate:**",
            "",
            _table(case["candidate"]),
            "",
            "**Verdicts:**",
            "",
        ]
        md += [f"- {name}: {verdict}" for name, verdict in case["verdicts"].items()]
        md += [
            "",
            f"**Reading (mine, a proposal):** {case['reading']}",
            "",
            f"Found on: {case['found_on']}. Attribution: UNDETERMINED.",
            "",
        ]
        for side, text in case.pop("inline").items():
            (out / "inline" / f"{case['task']}-{side}.sql").write_text(text, encoding="utf-8")
    (out / "clean-cases.md").write_text("\n".join(md), encoding="utf-8")
    (out / "clean-cases.json").write_text(
        json.dumps(cases, indent=1, default=str), encoding="utf-8"
    )
    for case in cases:
        print(case["task"], json.dumps(case["verdicts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
