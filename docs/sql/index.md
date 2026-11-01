# SQL pack

The SQL pack tests two read-only queries, a **reference** (gold) and a **candidate** (generated),
against valid changes to a database. It is the same idea as test-suite accuracy and bounded SQL
equivalence checking: a query pair can agree on today's rows by accident. For example,
`SUM(owed - collected)` and `SUM(owed) - SUM(collected)` agree on complete rows and differ as soon as
one amount is `NULL`.

## What you provide

| Input | Form | Required |
|---|---|---|
| The database | A SQLite file (with or without rows), or DDL for PostgreSQL, DuckDB or SQLite | Yes |
| The query pairs | Two `.sql` files for `sql check`, or a JSONL suite for `sql suite` | Yes |
| Domain rules | A JSON Schema file, see [Domain constraints](domain-constraints.md) | No, but without it findings stay [`STRUCTURAL`](../concepts/validity-and-fidelity.md#validity-tiers) |
| Seed and budgets | `--seed`, `--max-attempts` | No |

You do **not** write [hints](../concepts/hints.md). The pack harvests the tables, columns and literals your queries use
and tries each literal, its neighbors and its type edges.

## Commands

| Command | Does |
|---|---|
| `isitright sql check` | Audit one query pair |
| `isitright sql suite` | Audit a JSONL suite, with per-case isolation and ranking |
| `isitright sql replay REPORT` | Rebuild the first counterexample and reproduce both outputs |
| `isitright sql export REPORT --output F.jsonl` | Append counterexamples as new eval cases |
| `isitright sql slice` | Cut a small database holding the rows the reference query used |

All options are in the [CLI reference](../reference/cli.md).

## Engines

`--engine` is where the perturbed worlds run. The dialect of your queries and the engine are the
same choice for SQLite and PostgreSQL; DuckDB runs translated PostgreSQL SQL.

| `--engine` | Takes | [Fidelity](../concepts/validity-and-fidelity.md#execution-fidelity) |
|---|---|---|
| `sqlite` (default) | `--database FILE` or `--schema DDL` | `NATIVE_ISOLATED` |
| `postgres` | `--schema DDL` | `NATIVE_ISOLATED`, on a disposable local server |
| `duckdb` | `--schema DDL` (PostgreSQL) | `EMULATED`; re-executed on PostgreSQL when it is installed |

See [Engines and large databases](engines.md).

## How comparison works

Results compare as **multisets** unless the reference query has a top-level `ORDER BY`
(`--ordering auto`, the default). Columns match by position by default (`--column-policy`).
Floats compare with `isclose` (relative 1e-9, absolute 1e-12). The effective policy is recorded in
every report, so a reviewer can see what "the same" meant.

Set `--ordering unordered` when the question does not care about order even though the reference
sorts, and `--ordering ordered` when it does even though the reference does not sort.

## What the search tries

Starting from your rows (or one generated row per table, for a schema-only run), the generic
families apply to depth two: boundary values around harvested literals, NULL copies, duplicates, a
parent without children, repeated children, nullable foreign keys, and edge values. Schema-only runs
have no original-data comparison; the report marks it skipped, not matched.

## Limits that matter when you start

- One read-only `SELECT` per query, including CTEs. DDL, DML, `PRAGMA`, `ATTACH` and multiple
  statements are rejected.
- A documented subset of SQL and schemas; unsupported input is rejected rather than weakened. See
  [Supported SQL](supported-sql.md).
- The whole database is the base world and is read into memory once. For a large database, use
  `sql slice`.
- The search is heuristic. [`NOT_FOUND_WITHIN_BUDGET`](../concepts/evidence.md#divergence_status) is not equivalence.

## Where to go next

- [Audit a suite](audit-a-suite.md): from an existing eval set to a ranked report.
- [Domain constraints](domain-constraints.md): move findings from `STRUCTURAL` to `DOMAIN_VALIDATED`.
- [SQL setup with an LLM](../onboarding/sql.md): prompt templates for the manual parts.
