# Quick start: BigQuery and Presto/Trino

You will audit query pairs written in BigQuery's dialect from a table definition alone: no account,
no data, no warehouse. You will read a finding and what `found_on: EMULATED` means, replay it, fill
a query template, declare a uniqueness rule, compare the way a benchmark does, and then see (without
running it) how a finding is confirmed on your own engine. Everything printed below was produced by
the commands shown, offline.

Run these from a clone of the repository (see [Install](index.md)).

## 1. The table definition

`examples/sql/bigquery/schema.sql` is what `INFORMATION_SCHEMA.TABLES.ddl` returns for a table:
a qualified name, a nested column, no key.

```sql
CREATE TABLE `my-project.shop.orders`
(
  order_id INT64 NOT NULL OPTIONS(description="Order identifier"),
  customer STRING,
  items ARRAY<STRUCT<sku STRING, qty INT64>>
);
```

The two queries differ in one word. `reference.sql` uses `LEFT JOIN UNNEST(o.items)`, which keeps an
order whose `items` array is empty; `candidate.sql` uses `CROSS JOIN UNNEST(o.items)`, which drops
it. On any order that has line items they return the same rows.

## 2. Audit the pair

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/reference.sql --candidate examples/sql/bigquery/candidate.sql \
  --output-dir artifacts/quick-start-warehouse
```

```text
Live candidate states: . agreement  C difference  x rejected  ? error
Candidate states: .....C
Generated counterexample: queries diverge after a nested_edit mutation
Tested 6 generated database states using DuckDB 1.5.6 (emulating BigQuery).
Found a difference on a nested_edit state:
  Data: {"orders": [{"order_id": 10, "customer": null, "items": []}]}
  Reference returned: [[10, null]]
  Candidate returned: []
DuckDB accepted the supported schema; domain validity was not checked.
DuckDB is an approximation; this difference has not been confirmed on BigQuery (use --confirm).
```

(The command also prints the paths it wrote: `counterexample.sql`, `replay.json`,
`case_report.json` and `case_report.md`. DuckDB's version in the output is the one installed on the
machine that ran it.)

isitright read the table definition, generated worlds, and found one where the queries differ: one
order whose array is empty (a `nested_edit` mutation). Nothing touched BigQuery. The search runs on
DuckDB, which translates BigQuery's SQL, and **that is why the finding says `found_on: EMULATED`**:
DuckDB is a stand-in for BigQuery and agrees with it on the fixtures the repository checks (see
[BigQuery and Presto/Trino](../sql/warehouses.md#emulation-and-its-fidelity)), not everywhere. An emulated
finding can be an artifact of the translation. Only a run on the real engine, with the same world
inlined, makes it `verified_on: NATIVE_INLINE` (section 7).

## 3. Replay

```console
isitright sql replay artifacts/quick-start-warehouse/case_report.json
```

```text
Reproduced both query outputs on duckdb 1.5.6.
```

`counterexample.sql` in the same directory is a DuckDB script that rebuilds the minimized world;
`replay.json` is what `replay` reads.

## 4. A query template

Evals often carry a placeholder for a value the harness fills in. `--param NAME=VALUE` fills
`<NAME>` and `{{ NAME }}` in both queries before parsing; an unfilled placeholder is an error that
names it, and the values are recorded in the report (`extensions.sql.template`).

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/template_reference.sql \
  --candidate examples/sql/bigquery/template_candidate.sql \
  --param CUSTOMER=ann --output-dir artifacts/quick-start-template
```

```text
Live candidate states: . agreement  C difference  x rejected  ? error
Generated counterexample: queries diverge after a nested_edit mutation
Found a difference on a boundary+nested_edit state:
  Data: {"orders": [{"order_id": 10, "customer": "ann", "items": []}]}
  Reference returned: [[10, null]]
  Candidate returned: []
```

(An excerpt; the lines between are the progress marks and the count of states tested.) The world
holds a customer named `ann`, because the filled-in query reads `customer = 'ann'`: the value became
a boundary hint.

## 5. A uniqueness rule

Warehouse tables rarely declare keys, so the search can build two rows with the same value, which
your domain may forbid. `distinct_reference.sql` counts `COUNT(DISTINCT customer)` and
`distinct_candidate.sql` counts `COUNT(customer)`: they agree unless a customer has two orders.

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/distinct_reference.sql \
  --candidate examples/sql/bigquery/distinct_candidate.sql \
  --output-dir artifacts/quick-start-distinct
```

```text
Live candidate states: . agreement  C difference  x rejected  ? error
Generated counterexample: queries diverge after a duplicate mutation
  Reference returned: [[1]]
  Candidate returned: [[2]]
```

(An excerpt: the `Data:` line holds a text value the generator made up and is left out.) The report
adds a note under the finding's validity: *the divergence needs equal values in orders.customer,
which has no declared key or unique rule: this may be a validity gap rather than a query defect*.
Its tier is `STRUCTURAL` only. If each customer really has one order, say so in a constraints file
(`examples/sql/bigquery/constraints.yaml`: `x-unique: [[customer]]`, see
[Domain constraints](../sql/domain-constraints.md#uniqueness-without-a-key)) and run again:

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/distinct_reference.sql \
  --candidate examples/sql/bigquery/distinct_candidate.sql \
  --constraints examples/sql/bigquery/constraints.yaml --output-dir artifacts/quick-start-unique
```

```text
No disagreement found in 31 admitted generated states within the budget; this is not evidence of equivalence
Tested 31 generated database states using DuckDB 1.5.6 (emulating BigQuery).
No difference found in the states tested; this does not prove equivalence.
```

The finding is gone because the rule rules out its world, not because the queries are equivalent.
The rule here is invented for this page: **declare a rule only if it holds in your data**, because
a wrong rule hides real findings.

## 6. Compare the way a benchmark does

Spider 2.0's evaluator accepts a candidate whose result contains every reference column, at any
position. isitright's default does not. `contained_reference.sql` returns `order_id`;
`contained_candidate.sql` returns `customer, order_id`.

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/contained_reference.sql \
  --candidate examples/sql/bigquery/contained_candidate.sql \
  --output-dir artifacts/quick-start-strict
```

```text
Live candidate states: . agreement  C difference  x rejected  ? error
Candidate states: C
Generated counterexample: queries diverge after a baseline mutation
Tested 1 generated database state using DuckDB 1.5.6 (emulating BigQuery).
```

The strict result is a difference of column count (the report's difference says `column count
differs: reference=1, candidate=2`), found on an empty table. With the benchmark's options:

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/contained_reference.sql \
  --candidate examples/sql/bigquery/contained_candidate.sql \
  --column-policy contained --null-as-zero --output-dir artifacts/quick-start-contained
```

```text
No disagreement found in 97 admitted generated states within the budget; this is not evidence of equivalence
Tested 97 generated database states using DuckDB 1.5.6 (emulating BigQuery).
No difference found in the states tested; this does not prove equivalence.
```

Both are right about what they check. The comparison options are recorded in every report, so the
reader knows which rule produced the verdict. Use the benchmark's options when you want to know
what the benchmark would score; use the default when you want to know whether the queries return
the same thing.

## 7. Confirm on your own engine (shown, not run here)

These need an account or a server, so this page does not run them. Confirmation sends the minimized
world to the real engine as literal rows inside the query text:

```text
isitright sql check --dialect bigquery --schema schema.sql --reference gold.sql --candidate cand.sql \
  --confirm bigquery --bq-project MY_PROJECT --max-bytes-billed 10485760

isitright sql check --dialect presto --schema schema.sql --reference gold.sql --candidate cand.sql \
  --confirm connection --connection my_engine:run --trust-code
```

- **No table is read.** Every table reference is replaced by inline rows, and the final text is
  parsed again: if it still names a table (a table in a nested subquery, a second spelling, a view,
  one the schema did not include) it is **refused before anything is sent**, because the engine
  would otherwise read the real table and mix it into the small world. BigQuery then runs a dry run,
  refuses an estimate above 10 MB, caps the bytes billed and labels the job.
- `--confirm connection` uses a function you write, `run(sql) -> (columns, rows)`, loaded only with
  `--trust-code`: that is how a company's own Presto or PrestoDB is reached.
- A confirmed finding is `verified_on: NATIVE_INLINE`. One that does not reproduce natively is
  `INCONCLUSIVE` and listed as an emulation artifact. A failure to reach the engine leaves the finding
  unverified; it never confirms one.

For a local Trino, `examples/sql/trino/docker-compose.yml` starts a server that needs no data.
**It was not run for this page** (the Docker daemon was not running on the machine that wrote it);
the Trino fixtures were confirmed on a local Trino 484 for 0.7 and the compose file was tested then.

## 8. Your own schema and queries

Export the table definitions from your warehouse (`INFORMATION_SCHEMA.TABLES.ddl` for BigQuery,
`SHOW CREATE TABLE` for Presto and Hive), save them as `schema.sql`, write your gold and candidate
queries to files, and run step 2 with `--dialect bigquery`, `presto` or `trino`. For many cases at
once use `isitright sql suite` with a JSONL file. Add a constraints file as you learn what the
domain allows. See [BigQuery and Presto/Trino](../sql/warehouses.md) for the full reference.
