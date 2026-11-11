# Spider 2.0-lite, the BigQuery questions: schemagate end to end, scored by Spider 2.0's own evaluator

[Spider 2.0-lite](https://github.com/xlang-ai/Spider2) has 547 tasks: 205 on BigQuery (`bq*`, `ga*`), 207 on
Snowflake and 135 on SQLite. This folder is the **BigQuery 205**. The SQLite results are in
[`../spider2_lite_sqlite/`](../spider2_lite_sqlite/); Snowflake has not been run (the shared participant account
had not been granted at the time of writing).

## Result

| Setup | Correct | EX |
|---|---|---|
| **schemagate + Claude Sonnet 5.5, one query per question** | **94 of 205** | **45.9** |

Scored with `evaluation_suite/evaluate.py --mode exec_result` against Spider 2.0's released gold results, on the
CSV files in `claude-sonnet-5-5/` (`claude-sonnet-5-5.eval.txt` is its full output, `claude-sonnet-5-5.correct_ids.csv`
the ids it marked correct). The evaluator divides by the 190 CSVs it found and prints 49.5; the 15 tasks with no
result (4 declined twice, 11 whose query failed on every attempt) count as wrong here, so 94 / 205.

## What ran, per task

`benchmarks/spider2_lite.py --platform bigquery`, run on 2026-10-24:

1. the database's tables come from Spider 2.0's own metadata files (names, types, nested fields, column
   descriptions, sample rows); BigQuery's date-sharded families (`ga_sessions_20170101` ... 366 tables,
   `events_*`, `gsod<year>`, `ghcnd_*`) are offered as one wildcard table each, with the suffix range, which is how
   BigQuery documents querying them;
2. schemagate selects the tables the question needs (`top_k` 12, fewer if the schema text would pass 60,000
   characters);
3. the prompt gets those tables' DDL, the question's external-knowledge document when Spider 2.0 provides one,
   and a short note on BigQuery syntax;
4. the model writes **one** query; it runs on BigQuery (dry-run first, refused above 5 GB); an error goes back to
   the model, at most 3 repairs (25 tasks used one). A model that declines is asked once more for its best
   reading (32 tasks); 4 declined twice.

Per task the folder has `<id>.sql`, `<id>.csv` (its result) and `<id>.trace.md` (tables selected, every attempt,
every error, timestamps). `claude-sonnet-5-5_log.jsonl` is the run log. Nothing reads the gold SQL or the gold
results. 147 model calls; 66 GB scanned on BigQuery (inside the free tier).

## What to read with care

- **Two of three parts.** A leaderboard entry needs all 547 tasks; without Snowflake this is not one.
- **The first attempt was worse and is not shown as the result.** Before the shard families were collapsed, the
  model was offered random single days of `ga_sessions_*` and declined most GA questions. That run was stopped
  and redone from scratch with the fix; only the redone run is here.
- **One run, no repeats.** Treat it as about ±2 points.
