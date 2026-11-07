# BigQuery quick start (offline)

A constructed schema and a pair of queries that agree on any order with line items and differ on an
order whose `items` array is empty: `LEFT JOIN UNNEST` keeps the order, `CROSS JOIN UNNEST` drops it.
All files here are proposed fixtures written by the isitright authors.

```console
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/reference.sql --candidate examples/sql/bigquery/candidate.sql \
  --output-dir artifacts/bigquery-example
```

From the DDL alone, isitright finds a one-row world whose `items` array is empty, minimizes it and
writes `counterexample.sql` (a DuckDB script that rebuilds it) and `replay.json`. Nothing needs
BigQuery, an account or data. The finding is `found_on: EMULATED`:

```console
isitright sql replay artifacts/bigquery-example/case_report.json
```

## Optional: confirm on BigQuery

Confirmation sends the minimized world as literal rows inside the query text. It reads no table, and
the account needs only permission to run query jobs. Install the client and sign in first
(`gcloud auth application-default login`):

```console
python -m pip install "isitright[bigquery]"
isitright sql check --dialect bigquery --schema examples/sql/bigquery/schema.sql \
  --reference examples/sql/bigquery/reference.sql --candidate examples/sql/bigquery/candidate.sql \
  --confirm bigquery --bq-project MY_PROJECT --max-bytes-billed 10485760 \
  --output-dir artifacts/bigquery-confirmed
```

A confirmed finding has `verified_on: NATIVE_INLINE`. If the divergence does not reproduce, the case
is `INCONCLUSIVE` and the divergence is listed as an emulation artifact. See
`docs/sql/warehouses.md`.
