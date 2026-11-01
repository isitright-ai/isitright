# Engines and large databases

## Choosing an engine

Use the engine your queries target. Perturbed worlds run there, so the SQL semantics are the real
ones.

| Your queries target | Use | Input | Notes |
|---|---|---|---|
| SQLite | `--engine sqlite` | `--database FILE`, or `--schema DDL` | In-memory copies; your file is never opened for writing |
| PostgreSQL | `--engine postgres` | `--schema DDL` | Needs `isitright[postgres]`; a disposable local server is started and stopped for you. About 40 s per case when all 500 attempts are used |
| PostgreSQL, fast screening | `--engine duckdb` | `--schema DDL` (PostgreSQL) | Needs `isitright[duckdb]`. Emulation: see below |

SQLite takes either a database or DDL. PostgreSQL and DuckDB take DDL only: isitright does not
connect to your production PostgreSQL, and never modifies your data or systems.

```console
isitright sql check --engine postgres --schema examples/postgres/schema.sql \
  --reference examples/postgres/reference.sql --candidate examples/postgres/candidate.sql \
  --output-dir artifacts/postgres-example
```

### Getting DDL

Use your database's own schema dump, then check the result fits the
[supported subset](supported-sql.md): single-column primary keys, simple foreign keys, literal
defaults, and the listed types.

```console
pg_dump --schema-only --no-owner --no-privileges mydb > schema.sql
```

If the dump has features outside the subset (composite keys, `GENERATED ALWAYS` identity, views,
triggers), the run fails with an error that names the construct. You can edit a copy of the DDL down
to the tables the queries use. This changes the world the audit covers, so keep that copy with the
report.

## Schema-only runs

With DDL and no rows, isitright synthesizes a starting state: one generated row per table, with
references matched. It then applies the families to depth two. There is no original-data comparison;
the report marks that skipped, not matched. A SQLite file whose tables are all empty is treated the
same way. A database with any rows is perturbed from its own rows.

## Emulation and native verification

DuckDB is a candidate generator, not evidence. When the PostgreSQL extra is installed, every state
on which DuckDB reports a divergence is re-executed on a disposable PostgreSQL instance
(`--verify-native`, on by default; `--no-verify-native` turns it off):

| Native result | Status |
|---|---|
| The results differ there too | [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status), `found_on: EMULATED`, `verified_on: NATIVE_ISOLATED`. May fail CI under `--fail-on` |
| The results agree there | An **emulation artifact**: not a counterexample, counted under `search.rejected.emulation_artifact`, listed in `extensions.sql.emulation_artifacts` |
| PostgreSQL is unavailable or the rerun fails | Stays emulated and `NOT_VERIFIED`, with the reason. Never fails CI |

[Minimization](../concepts/minimization-and-replay.md) keeps the native disagreement, so a minimized world is verified too.

**Integer division.** PostgreSQL divides two integers with truncation (`5 / 2` is 2); DuckDB gives
2.5. The translation rewrites every `/` whose operands are both integers, by declared column types
and literals, to a truncating division, guarded so a zero divisor is an error as in PostgreSQL. A
division whose types cannot be read is left as written and counted under
`extensions.sql.integer_division.uncertain`. `numeric / integer` is not translated (it is exact in
PostgreSQL), and floating-point division by zero is reported inconclusive.

DuckDB may reject or behave differently on some supported PostgreSQL features, such as identity
columns. Its findings remain labeled emulated.

## Large databases

The whole database is the base world, read into memory once, so a database with many rows makes each
case slow. Cut a small database from it:

```console
isitright sql slice --database big.sqlite --reference ref.sql --output slice.sqlite
isitright sql check --database slice.sqlite --reference ref.sql --candidate cand.sql
```

```text
Wrote slice.sqlite: 3 rows, 3 joined tuples.
```

The slice holds the rows the reference query used: up to `--cap` joined tuples (default 25), closed
under foreign keys, plus `--pad` rows (default 5) of each table that only a subquery names.

!!! warning "The audit then covers worlds near the slice"
    [Mutations](../concepts/worlds-and-mutations.md#mutations) apply to the slice, not to the original database. Keep the slice with the report and say
    so when you share a finding. A slice is for a query-by-query audit, so cut one per reference query
    in a suite (a loop over your cases).

## Known SQLite limitation

A database whose foreign keys reference columns that are not the parent's primary key or unique
(SQLite reports `foreign key mismatch`) cannot be opened, because SQLite cannot enforce them.
