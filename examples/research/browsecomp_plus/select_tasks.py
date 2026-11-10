"""Choose the demo's tasks by a rule, before any audit runs. Writes selection.json.

The rule (fixed here, recorded in DECISIONS.md before the first audit): in the order of query id,
take a query when
  1. its gold documents number one to three (a gold set small enough to restrict a world to),
  2. the published BM25 + gpt-5 run on it completed and made at least one search, and
  3. that run's "Exact Answer" equals the gold answer after the pack's string normalization
     (so the baseline is a passing eval under an exact comparison, which is what the audit's gate
     needs),
up to LIMIT queries. No audit result is used.

    python select_tasks.py --data D:/Data/browsecomp-plus --out D:/Data/bcp-work/selection.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import decode_run, iter_queries, iter_runs, normalize_answer, parse_final

LIMIT = 25


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runs = {r["query_id"]: r for r in iter_runs(args.data / "runs" / "bm25-gpt5.jsonl")}
    stages = {
        "queries": 0,
        "gold_docs_1_to_3": 0,
        "run_completed_with_search": 0,
        "answer_matches": 0,
    }
    chosen = []
    queries = sorted(
        iter_queries(args.data, ("query_id", "answer", "gold_docs")),
        key=lambda q: int(q["query_id"]),
    )
    for q in queries:
        stages["queries"] += 1
        if not 1 <= len(q["gold_docs"]) <= 3:
            continue
        stages["gold_docs_1_to_3"] += 1
        run = runs.get(q["query_id"])
        if run is None or run["status"] != "completed":
            continue
        decoded = decode_run(run)
        if not decoded["searches"] or decoded["final"] is None:
            continue
        stages["run_completed_with_search"] += 1
        _, answer = parse_final(decoded["final"])
        if answer is None or normalize_answer(answer) != normalize_answer(q["answer"]):
            continue
        stages["answer_matches"] += 1
        if len(chosen) < LIMIT:
            chosen.append(q["query_id"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"limit": LIMIT, "count": len(chosen), "stages": stages, "ids": chosen}, indent=2
        ),
        encoding="utf-8",
    )
    print(json.dumps({"count": len(chosen), "stages": stages, "ids": chosen}))


if __name__ == "__main__":
    main()
