# BigQuery and Presto/Trino

The SQL pack audits queries written for BigQuery and for Presto or Trino (including Presto over
Hive tables). You give it the table definitions, not the data. The search runs on DuckDB; a finding
can then be confirmed on your own engine with the state written into the query text.

!!! note "Every finding starts as emulated"
    DuckDB is not BigQuery and is not Presto. A finding is reported `found_on: EMULATED` until a
    native host re-runs it and gets the same disagreement (`verified_on: NATIVE_INLINE`). A
    divergence that does not reproduce natively is an emulation artifact: it is counted and
    listed, and it is not a counterexample.

!!! warning "Confirmation needs an extra that `isitright[all]` does not install"
    `pip install "isitright[bigquery]"` or `pip install "isitright[trino]"`, only if you want to
    confirm findings on your own engine. `isitright[all]` leaves both out on purpose (a cloud client
    stack you may never use). Searching and reporting need neither. Without the extra,
    `--confirm bigquery` stops with a message that names the one to install.

## Dialects, engines and confirmation

`--dialect` is the SQL your queries are written in. `--engine` is where generated states run.
`--confirm` names the native host that re-runs findings.

| `--dialect` | Runs on | Confirm with | Notes |
|---|---|---|---|
| `sqlite`, `postgres` | as before | as before | `--engine` alone keeps its old meaning |
| `bigquery` | DuckDB (`EMULATED`) | `--confirm bigquery` | Needs `isitright[bigquery]` for confirmation only |
| `presto` | DuckDB (`EMULATED`) | `--confirm connection` or `--confirm trino` | Hive-style DDL is accepted too |
| `trino` | DuckDB (`EMULATED`) | `--confirm trino` or `--confirm connection` | Same translations as `presto`; no fixture tells the two apart yet |

```console
isitright sql check --dialect bigquery --schema schema.sql \
  --reference gold.sql --candidate candidate.sql --output-dir artifacts/bq
```

A runnable offline example is in `examples/sql/bigquery/`.

## Table definitions

Give DDL for the tables your queries read: `CREATE TABLE` statements, in any order.

| Engine | Where to get it |
|---|---|
| BigQuery | ``SELECT ddl FROM `project.dataset`.INFORMATION_SCHEMA.TABLES WHERE table_name = 't'`` (nested types and column descriptions included) |
| Presto/Trino | `SHOW CREATE TABLE catalog.schema.t` |
| Hive | `SHOW CREATE TABLE t` |

`bq show --schema` prints JSON, which isitright does not read; use the `INFORMATION_SCHEMA` query.

Names: a table is named by the last part of its qualified name (`project.dataset.table` becomes
`table`). If two tables share it, they become `dataset_table`. A query may write the table with any
trailing part of the full name (`table`, `dataset.table`, `project.dataset.table`); a name that
fits two tables is an error that lists both.

**Keys are optional.** A table without one works in every dialect. Keys a warehouse declares but
does not enforce (BigQuery `PRIMARY KEY (...) NOT ENFORCED`) are imported as keys and reported as
declared, not enforced.

**Partitions are ordinary columns** (BigQuery `PARTITION BY`, Presto `partitioned_by`, Hive
`PARTITIONED BY`). A partition filter's literal becomes a boundary value like any other.

### Why declaring uniqueness matters

Without a declared key the search may build two rows with the same identifier. In a warehouse that
is often impossible in the domain, and it is the main source of false findings. For
`COUNT(DISTINCT user_id)` against `COUNT(user_id)` the search finds two rows with the same
`user_id`, at the `STRUCTURAL` tier, and the report says so:

> the divergence needs equal values in t.user_id, which has no declared key or unique rule: this may
> be a validity gap rather than a query defect

Declare the rule in the [constraints file](domain-constraints.md) and the finding goes away:

```yaml
properties:
  t:
    x-unique: [[user_id]]          # or, on a column: items.properties.user_id.x-unique: true
```

## Query templates

`--param NAME=VALUE` fills `<NAME>` and `{{ NAME }}` placeholders in both queries before they are
parsed (`WHERE ds = '<LATEST_DS>'`, Airflow's `{{ ds }}`). There is no template logic. `<NAME>` is a
placeholder only when NAME is upper case, so `a<b` is untouched. An unfilled placeholder is an
error that names it. The values and the original texts are recorded in
`extensions.sql.template`. In a JSONL suite, a case may carry a `params` object.

## Nested types

`ARRAY` and `STRUCT` (BigQuery), `ARRAY`, `MAP` and `ROW` (Presto), at any depth.

- State values are JSON: a struct is a mapping, an array a list, a map a list of `[key, value]`
  pairs. The declared type stays with the column, so loading into an engine is exact.
- **Generation is scoped to the columns the queries read** (by `UNNEST`, dot access, or a function
  on the column). A nested column no query reads is NULL if it can be, else its smallest valid
  value; a referenced array holds one element, so emptying it is a change. This keeps a Google
  Analytics row (hundreds of nested fields) small.
- **Known limit: scoping is per column, not per path inside it.** If a query reads only
  `items[].qty`, the whole `items` column is still generated and mutated, `sku` included.
  That costs search budget (it is spent on fields no query reads) and can leave extra
  fields in a counterexample; it never produces a wrong finding. Per-path scoping is
  planned: it needs the references resolved through `UNNEST`, joins, CTEs and subqueries.
- **Mutations**: an array emptied or set to NULL, an element set to NULL, removed or duplicated,
  elements reversed, a struct field or a struct set to NULL, a map entry removed. Map entries are
  never reordered. Numeric leaves are moved by the JSON family.
- **Validity depends on the dialect.** BigQuery stored tables cannot hold a NULL array (it is stored
  as an empty array) or a NULL array element, so such worlds are not generated for BigQuery.
  Presto allows both. A NULL array and an empty array are different values inside a query.
- **Results**: arrays compare in order, structs by field, maps without order. For BigQuery, a NULL
  array in a result counts as an empty array, and a result containing an array with a NULL element
  is a query error for that world.
- **Minimization** shrinks rows and then the arrays inside them.

The `UNNEST` lead example, `LEFT JOIN UNNEST(t.tags)` against `CROSS JOIN UNNEST(t.tags)`, agrees on
rows whose array has elements and differs on a row whose array is empty (or NULL, in Presto). From
DDL alone isitright finds that world and minimizes it to one row.

## Emulation and its fidelity

Each dialect has fixtures (`tests/warehouse_fixtures.py`): one query, a fixed state, the outcome on
the emulation, the outcome the engine documents, and a status.

| Status | Meaning |
|---|---|
| `agrees` | DuckDB and the documented outcome are the same without any rewrite |
| `translated` | A plain SQLGlot transpile would differ or lose the construct; the pack rewrites it exactly |
| `checked` | A rule applied when results are read (BigQuery's NULL arrays and NULL elements) |
| `detected` | The pack refuses the query and names the construct |
| `listed` | A known divergence, neither translated nor detected (below) |

Translated today: `UNNEST ... WITH OFFSET` (0-based in BigQuery, 1-based in DuckDB), `ARRAY_AGG(x
IGNORE NULLS ...)`, out-of-range `arr[OFFSET(n)]` (an error in BigQuery) and `SAFE_OFFSET` (NULL,
including negative indexes), division by zero (an error in BigQuery), `EXTRACT(DAYOFWEEK ...)`,
`DATE_TRUNC` (its week and its DATE result type), the session time zone (UTC), Presto integer
division and array and map subscripts. SQLGlot's own "unsupported" warnings are errors here. A
silent divergence that nobody listed is found only by a fixture; add one when you find one.

A documented outcome is not a confirmed one. The expected outcomes are confirmed natively by the
BigQuery runbook or on a local Trino. Both have run: the BigQuery smoke test (2026-11-07) and a local Trino 484 in Docker (2026-11-08, `examples/sql/trino/smoke.py`). The 23 BigQuery fixtures it sent and the 15 Presto fixtures say `confirmed=True`; the 3 `detected` BigQuery fixtures were not sent. Trino is not PrestoDB: the Presto fixtures are confirmed on Trino only.

**Listed, not translated**: `numeric / integer` is exact decimal division in Presto and floating
point in DuckDB; floating-point results can differ in the last digits; regular-expression flavors,
collations and string formatting functions follow DuckDB. A query error on one side of a pair on a
generated world skips that world; it is not a finding.

## Confirming a finding

Only the worlds of a finding are sent. First the minimized world; if it does not reproduce, the
unminimized divergent world. Both outcomes are in `native_confirmation`. Each confirmation is two
queries.

The text sent has every table replaced by inline rows, typed so that an empty table and an empty
array are well typed:

- BigQuery: `(SELECT * FROM UNNEST([STRUCT<id INT64, tags ARRAY<INT64>>(1, [1, 2])]))`
- Presto/Trino: `(SELECT * FROM (VALUES (CAST(1 AS BIGINT), CAST(ARRAY[1, 2] AS ARRAY(BIGINT)))) AS v(id, tags))`

### Why the host refuses SQL that still names a table

A reference the rewrite misses (a table in a nested subquery, a second spelling of a name, a view, a
table the schema did not include) would make the engine read the real table for that part of the
query, silently. The result would mix the small world with production rows and could confirm a
finding that does not exist. The scan would be billed. Through a connection you supply, it would
read production data with your permissions. So the final text is parsed again and sent only if every
table it names is an inline one. The check runs on the text to be sent, before any client call.
For BigQuery the dry run's byte estimate, which should be near zero, is a second guard.

### BigQuery

```console
python -m pip install "isitright[bigquery]"
isitright sql check --dialect bigquery --schema schema.sql --reference gold.sql \
  --candidate candidate.sql --confirm bigquery --bq-project MY_PROJECT --max-bytes-billed 10485760
```

Every confirmation query is dry-run first; it is refused if the estimate is above 10 MB and
otherwise run with `maximum_bytes_billed` set to `--max-bytes-billed` and job labels
(`isitright=1`, `isitright_phase=confirm`). A query over about 900,000 characters is not sent.
Credentials are read by Google's client library from application-default credentials
(`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`; `--env-file` reads
only that one variable from a file. isitright never prints, logs or writes a credential into a
report. The account needs permission to run query jobs (`roles/bigquery.jobUser`) and nothing else:
inline queries read no tables.

### Your own engine

If isitright cannot reach your engine (an internal Presto, for example), give it a function that
runs SQL and returns rows. It needs `--trust-code` because it is your code.

```python
# my_engine.py
from my_company import client  # your internal client


def run(sql: str):
    cursor = client.connect().cursor()
    cursor.execute(sql)
    columns = [d[0] for d in cursor.description]
    return columns, [list(row) for row in cursor.fetchall()]
```

```console
isitright sql check --dialect presto --schema t.sql --reference gold.sql --candidate cand.sql \
  --confirm connection --connection my_engine:run --trust-code
```

isitright sends only inline text, one query per call. No table has to exist and no data leaves your
network: the search ran offline from DDL, and the engine sees only query text.

### Trino

`--confirm trino` uses the `trino` client (`isitright[trino]`, not part of `isitright[all]`)
against `--trino-host`, `--trino-port`, `--trino-catalog` and `--trino-schema`. A local server is
enough, since the query reads no table.

If you have no Trino server, run one in Docker. The repository has a compose file
(`examples/sql/trino/docker-compose.yml`) that starts the version the 0.7 fixtures were confirmed
on, on `127.0.0.1:8080` with the `memory` catalog (the defaults of `--trino-host`, `--trino-port`
and `--trino-catalog`):

```console
docker compose -f examples/sql/trino/docker-compose.yml up -d --wait
python -m pip install "isitright[trino]"
isitright sql check --dialect trino --schema schema.sql --reference gold.sql \
  --candidate candidate.sql --confirm trino
docker compose -f examples/sql/trino/docker-compose.yml down
```

Without the compose file, one command does the same:
`docker run --rm -d --name isitright-trino -p 127.0.0.1:8080:8080 trinodb/trino:484`. The server
needs about 30 to 60 seconds to start; `curl http://127.0.0.1:8080/v1/info` shows
`"starting":false` when it is ready. Stop it with `docker stop isitright-trino`. The container holds
no data of yours: the confirmation queries read no table.

## Costs and safety

- The search never runs on the warehouse.
- Schema-only is the default: no production row leaves the warehouse.
- A confirmation is two queries per world, at most two worlds.
- The host cannot be made to run DDL, DML or a second statement.
- Not protected: a function you supply is trusted code, and a query that is itself expensive on
  inline data is limited only by the bytes cap and your engine's own limits.

## Candidate errors

A candidate that raises an error on a valid world where the reference returns a result is a finding
of its own kind, labeled **candidate errors** (`divergence.kind` is `candidate_errors`; the headline
and the difference say so). Example: the reference uses `SAFE_CAST(s AS INT64)` and the candidate
`CAST(s AS INT64)`; on a row where `s` is `'abc'` BigQuery returns NULL for the first and raises
`Bad int64 value` for the second.

- Only an error that depends on the data counts: a failed conversion, an overflow, a division by
  zero where the engine raises, an array with a NULL element in a BigQuery result. A parse, bind or
  catalog error does not (it would show on every world and means the translation, not the
  candidate, is wrong), and neither does a timeout or a row-limit stop.
- The reference erroring, or both erroring, is still no finding.
- The error is first seen on DuckDB. **Confirm it natively** (`--confirm bigquery` or
  `--confirm trino`): the host then runs both queries with the state inlined, and the finding is
  `VERIFIED` only if the candidate errors there too. If it does not, the finding is an emulation
  artifact and is excluded, as for any other divergence. On BigQuery the error must come from running
  the query: an error at the dry run is a static error and leaves the finding unverified. A Trino
  server reports static and run-time errors alike, so there the check cannot tell them apart.
- This applies to the BigQuery, Presto and Trino dialects. SQLite and PostgreSQL keep their earlier
  rule (a query error on a world skips that world).
- In the report the candidate's result is one `query_error` column holding the first line of the
  error message, so a replay and an exported eval case reproduce it.

## Comparing the way a benchmark does

Spider 2.0's evaluator needs options the strict default does not have, all recorded in the report:
`--column-policy contained` (each reference column equals some candidate column, at any position),
`--reference-columns 0,2` (only those reference columns), `--column-vectors`, `--null-as-zero`, and
`--float-atol 0.01`. With unordered comparison, columns are compared as independent sorted vectors.

## Demos

- `examples/sql/bigquery/`: a constructed schema and two queries, offline, a few seconds.
- `examples/sql/spider2/`: the BigQuery tasks of Spider 2.0-lite whose published gold SQL passes in a published schemagate run (73 selected by a rule fixed before any audit ran; the rule and commits are in `selection.json`). Each task is audited from its table definitions only, under Spider's comparison settings and under isitright's strict default. Findings are emulated; none is confirmed on BigQuery unless you run the BigQuery steps. The scripts are `prepare.py` (selects and copies from two local clones), `run_demo.py` and `bigquery_steps.py`; the third-party licences are in `licenses/`. These are proposed fixtures, not a benchmark result.

## Not supported in 0.7

Wildcard tables (rewritten in the Spider demo copy only), scripting (`DECLARE`, multiple
statements), `MERGE` and other DML, geography types and `ST_` functions, BigQuery `JSON`,
`BIGNUMERIC`, `INTERVAL`, an implicit correlated unnest (`FROM t, t.arr`), `LIMIT` inside
`ARRAY_AGG`, `EXTRACT(WEEK ...)`, `DATE_TRUNC` on an expression whose type cannot be determined,
Snowflake, Spark SQL, BigQuery ML, and running the search on a warehouse.
