# Quick start: SQL

You will audit one query pair, read the counterexample, [replay](../guides/replay-and-export.md) it, export it as a new eval case,
and then audit a small suite. It runs offline on SQLite.

Run these from a clone of the repository (see [Install](index.md)).

## 1. Create a database

```console
python examples/sqlite/create_database.py example.sqlite
```

The `tribute` table has three rows. Two queries answer "what is the total outstanding amount?":

```sql
-- reference.sql: sum only per-record shortfalls whose two operands are known
SELECT SUM(amount_owed - amount_collected) FROM tribute;
-- candidate.sql: sum each column independently, then subtract the totals
SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute;
```

On the three rows both return `130.0`. Execution accuracy would pass the candidate.

## 2. Audit the pair

```console
isitright sql check --database example.sqlite \
  --reference examples/sqlite/reference.sql --candidate examples/sqlite/candidate.sql \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start
```

```text
Live candidate states: . agreement  C difference  x rejected  ? error
Candidate states: C
Generated counterexample: queries diverge after a missing mutation
Wrote artifacts\quick-start\counterexample.sql
Wrote artifacts\quick-start\replay.json
Wrote artifacts\quick-start\case_report.json
Wrote artifacts\quick-start\case_report.md
```

isitright took the database, added a copy of a row with `amount_collected = NULL` (the `missing`
family), checked that the new world obeys the schema and the rules in `constraints.yaml`, and ran
both queries on it. They differed.

## 3. Read the result

Open `case_report.md`. The parts to read first:

```text
Observed difference: First differing row is 1: reference [SUM(amount_owed - amount_collected)=70.0];
candidate [SUM(amount_owed) - SUM(amount_collected)=170.0].
```

`counterexample.sql` is the [minimized](../concepts/minimization-and-replay.md) world, small enough to read:

```sql
CREATE TABLE tribute (...);
INSERT INTO "tribute" VALUES (3, 'south', 80.0, 10.0);
INSERT INTO "tribute" VALUES (4, 'north', 100.0, NULL);
```

The report started from 4 rows and reduced to 2. The technical details table says what kind of
evidence this is:

| Field | Value | Meaning |
|---|---|---|
| Divergence status | [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status) | The queries disagree on a tested world |
| Validity | `STRUCTURAL, DOMAIN_VALIDATED` | Keys and types hold, and so does every rule in `constraints.yaml` |
| [Execution fidelity](../concepts/validity-and-fidelity.md#execution-fidelity) | `NATIVE_ISOLATED` | Run in a real SQLite, on an in-memory copy |
| Review classification | `UNDETERMINED` | isitright does not say which query is wrong |

Here the reference is right and the candidate is wrong, but only you can decide that. Read
[Evidence](../concepts/evidence.md) for what each field does and does not claim.

## 4. Replay and export

```console
isitright sql replay artifacts/quick-start/case_report.json
isitright sql export artifacts/quick-start/case_report.json --output evals/generated.jsonl
```

Replay rebuilds the minimized world from the concrete rows in the report (not from a seed) and
checks that both outputs reproduce. Export appends an eval case to a JSONL file: a fixture state,
both queries and the expected disagreement. See [Replay and export](../guides/replay-and-export.md).

## 5. Audit a suite

A suite is a JSONL file with one query pair per line:

```json
{"case_id": "null-shortfall", "question": "What is the total outstanding amount?", "reference_sql": "SELECT SUM(amount_owed - amount_collected) FROM tribute", "candidate_sql": "SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute"}
```

```console
isitright sql suite --database example.sqlite --cases examples/sqlite/cases.jsonl \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start-suite
```

```text
3 cases | 1 agreement | 2 counterexamples | 0 inconclusive | 0 unsupported
Review:
  C null-shortfall  counterexample | domain-validated | missing
  C province-count  counterexample | domain-validated | missing
```

`suite_report.md` ranks cases by evidence strength: domain-validated counterexamples first. The
third case agrees. That means no difference was found within the budget (500 candidate worlds by
default), not that the two queries are equivalent.

## 6. The same from Python

```python
from isitright import check

report = check(
    engine="sqlite",
    database="example.sqlite",
    reference_sql="SELECT SUM(amount_owed - amount_collected) FROM tribute",
    candidate_sql="SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute",
)
print(report.divergence_status, report.headline)
```

## Next

- Audit your own eval set: [Audit a suite](../sql/audit-a-suite.md). If the setup feels like a lot of
  manual work, [SQL setup with an LLM](../onboarding/sql.md) drafts the pieces.
- Target PostgreSQL: [Engines and large databases](../sql/engines.md).
- Write domain rules so counterexamples reach [`DOMAIN_VALIDATED`](../concepts/validity-and-fidelity.md#validity-tiers):
  [Domain constraints](../sql/domain-constraints.md).
