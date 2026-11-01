# Audit a suite

This guide takes an existing text-to-SQL eval set, the cases that currently pass, and produces a
ranked report of the ones whose pass depends on the data.

## 1. Pick the cases

Audit the cases that **pass** your current metric (execution accuracy, an LLM judge). Cases that
already fail do not need a perturbed world to show a problem.

## 2. Write the suite file

One JSON object per line, UTF-8:

```json
{"case_id": "q17", "question": "What is the total outstanding amount?", "reference_sql": "SELECT ...", "candidate_sql": "SELECT ..."}
```

| Field | Required | Notes |
|---|---|---|
| `case_id` | Yes | Stable and unique. Reports and exports refer to it |
| `reference_sql` | Yes | The gold query |
| `candidate_sql` | Yes | The query your model produced |
| `question` | No | Shown in the report to help review |
| anything else | No | Kept as metadata in the report |

A suite audits **one database**, so group cases by database and write one file each. If you are
starting from a benchmark's files, this script splits BIRD-style `dev.json` and a predictions file
(adjust the field names if your files differ):

```python
import json
from collections import defaultdict
from pathlib import Path

dev = json.loads(Path("dev.json").read_text(encoding="utf-8"))
predictions = json.loads(Path("predict_dev.json").read_text(encoding="utf-8"))
# Optional: audit only cases that passed execution accuracy (one question_id per line).
passing = set(Path("ex_passing.txt").read_text().split()) if Path("ex_passing.txt").exists() else None

suites = defaultdict(list)
for index, item in enumerate(dev):
    case_id = str(item.get("question_id", index))
    if passing is not None and case_id not in passing:
        continue
    candidate = predictions[str(index)].split("\t----- bird -----\t")[0]
    suites[item["db_id"]].append({
        "case_id": f"{item['db_id']}-{case_id}",
        "question": item["question"],
        "reference_sql": item["SQL"],
        "candidate_sql": candidate,
        "evidence": item.get("evidence", ""),  # extra fields are kept as metadata
    })

Path("suites").mkdir(exist_ok=True)
for db_id, cases in suites.items():
    lines = (json.dumps(case, ensure_ascii=False) for case in cases)
    Path("suites", f"{db_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
```

## 3. Run

SQLite database with rows:

```console
isitright sql suite --database data/shop.sqlite --cases suites/shop.jsonl \
  --constraints rules/shop.yaml --output-dir artifacts/shop-suite
```

PostgreSQL from DDL (a disposable local server is started for you):

```console
isitright sql suite --engine postgres --schema schema.sql --cases suites/shop.jsonl \
  --output-dir artifacts/shop-suite
```

Each case is isolated: one case that is unsupported or fails does not stop the others. Budgets are
per case: `--max-attempts` candidate worlds (default 500) and `--minimization-attempts` (default 500).
SQLite uses about 0.2 s per case when all 500 attempts are used, DuckDB about 17 s and PostgreSQL
about 40 s. Add `-q` for totals only or `-v` for every case.

## 4. Read the ranking

The console prints one line per case and a legend:

```text
3 cases | 1 agreement | 2 counterexamples | 0 inconclusive | 0 unsupported
Review:
  C null-shortfall  counterexample | domain-validated | missing
```

`suite_report.md` and `suite_report.json` rank cases by evidence strength: domain-validated
counterexamples, then structural-only, then inconclusive or unsupported, then not found. Per-case
reports are under `cases/`. The suite totals count each status and each [mutation](../concepts/worlds-and-mutations.md#mutations) family.

Review the top of the list first, and read [Reviewing findings](../onboarding/triage.md) before
changing any gold query: the reference may be the wrong side.

## 5. Make evidence stronger

If most counterexamples are [`STRUCTURAL`](../concepts/validity-and-fidelity.md#validity-tiers) only, write [domain constraints](domain-constraints.md).
If a counterexample is an obviously absurd world, a rule is missing. If the database is large and
cases are slow, use [`sql slice`](engines.md#large-databases).

## 6. Grow your eval set

```console
isitright sql export artifacts/shop-suite/cases/0001-<case_id>/case_report.json --output evals/generated.jsonl
```

Each exported case contains a fixture state, both queries and the expected disagreement.
`rerun_eval_case` rebuilds the state and checks the queries still disagree as recorded. See
[Replay and export](../guides/replay-and-export.md).

## 7. Gate CI

```console
isitright sql suite ... --fail-on domain-counterexample
```

Exit code `3` means the policy triggered. See [Use in CI](../guides/ci.md).
