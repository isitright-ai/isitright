# Contract reference (version 0.4)

Behavior that scripts, CI and other tools may rely on. Anything not listed here may change
between pre-1.0 releases. The extension API (`isitright.core.*`) is public and **experimental**
until a pack is written by someone other than its author.

## Architecture

```text
src/isitright/
  core/      world, entities, constraints, hints, mutations, families/, search, stochastic,
             minimize, replay, evidence, values (Hypothesis edge values)
  packs/sql/ DDL and database to entities, SQLite / PostgreSQL / DuckDB hosts, SQLGlot hints,
             result comparator, reports, replay, eval-case export
  packs/mcp/ scenario model, simulated-service runtime, oracle, world generation, MCP host,
             runner, serve, replay, audit
  cli.py
```

The core knows nothing about SQL or MCP. A pack maps its worlds into the entity model, supplies
hosts with a stated fidelity, a comparator or oracle, and its own hint kinds. Report models use
Pydantic. The only runtime dependencies besides the standard stack are `hypothesis` (value
strategies inside families), `jsonschema`, `pydantic`, `pyyaml`, `sqlglot` and `typer`; `mcp`,
`duckdb` and PostgreSQL support are extras.

## Report schema 0.4

One schema, [`schemas/report-0.4.schema.json`](../schemas/report-0.4.schema.json), exported by
`tools/export_schemas.py` from `isitright.core.evidence.AuditReport`. Older report schemas are
removed. An `AuditReport` has `schema_version` (`"0.4"`), `pack`, `kind` (`case`, `suite` or
`scenario`), `cases`, `totals` and `elapsed_seconds`. Each `CaseReport` keeps these apart:

| Field | Values |
|---|---|
| `divergence_status` | `COUNTEREXAMPLE_FOUND`, `NOT_FOUND_WITHIN_BUDGET`, `INCONCLUSIVE`, `UNSUPPORTED` |
| `validity` | `status` (`VALID`, `INVALID`, `INDETERMINATE`, `NOT_ASSESSED`) and `tiers` (`STRUCTURAL`, `DOMAIN_VALIDATED`, `REACHABLE`, `TASK_CONSISTENT`, `OBSERVABLE`, `SIMULATOR_CONSISTENT`) |
| `execution_fidelity` | `found_on` (`NATIVE_ISOLATED`, `NATIVE_INLINE`, `EMULATED`, `SIMULATED`, `GENERATED`, `REPLAY_ONLY`), `verified_on`, `engine` |
| `oracles` | name, kind (`REFERENCE_PROGRAM`, `INVARIANT`, `RELATIONAL`, `CONSTRUCTIVE`, `JUDGE`), outcome (`MET`, `NOT_MET`, `CANNOT_JUDGE`), limits |
| `subject_kind` | `ARTIFACT`, `FROZEN_ARTIFACT`, `AGENT` |
| `stability` | `k`, baseline and world `counts`, and a `rate_claim` (test, pair counts, p-value) only with adequate evidence |
| `attribution_status` | `UNDETERMINED` by default; reserved: `AGENT_DEFECT`, `REFERENCE_DEFECT`, `AMBIGUOUS_TASK`, `POLICY_AMBIGUOUS`, `TOOL_CONTRACT_AMBIGUOUS`, `SIMULATOR_DEFECT` |
| `search` | seed, attempts, valid candidates, executed, rejections by reason, families run and skipped, budget per hint group (`hinted`, `unhinted`), hints used, depth reached, budget |
| `findings` | per finding: world, validity, oracle results, stability, world diff, mutation path (family, target, description, hints, atoms), pack-specific `divergence`, fidelity, replay, minimization |
| `worlds`, `controls` | every world with role and counts; `DISCRIMINATING`, `NOT_DISCRIMINATING` or `NOT_APPLICABLE` |
| `headline` | one line derived from the above; it never says pass, fail, correct or wrong (the model rejects it) |
| `extensions` | pack-specific fields (`sql`, `mcp`); not part of the common contract |

The status and the findings must agree, an unsupported case has no executed worlds, and a DuckDB
result must be labeled `EMULATED` (a PostgreSQL or SQLite one must not). `NOT_FOUND_WITHIN_BUDGET`
means no disagreement was found in the states tested within the budget; it is never a claim of
equivalence or correctness. An observed failure is never presented as a rate change.

## Mutations, hints and constraints (core)

- **Mutation**: data with a `family`, `target` (`state`, `response`, `timing`), `description`,
  `edits` (`set`, `unset`, `add`, `remove`, `param`), the `atoms` it touched and the `hints` that
  led to it. A world is a state plus response edits and timers and the path of mutations.
- **Families**: boundary, missing, key collision, duplicate, tie, empty, dangling, reference
  swap, cardinality boundary, prior operation, split, representation, out-of-scope extreme,
  temporal, units, service parameter, response edits, timing and edge values. Each declares the
  hint kinds it consumes. They are generic over the entity model.
- **Hints**: `kind`, `name`, `provenance` (`declared`, `harvested:program|schema|trace`, `proposed`
  reserved), `args`. Paths are dotted (`collection.field`, `collection.embedded.field`), `$name`
  refers to another hint, `@name` to a state parameter, and `where` clauses use the constraint
  expression language. A path that does not resolve is an error at load time. Hints prioritize;
  unhinted mutations still run on the remaining budget.
- **Constraints**: `Range`, `OneOf`, `NotNull`, `Unique`, `FunctionalDependency`, `Aggregate` and
  row expressions serialize to JSON. Python predicates are check-only and listed under
  `unused_rules`.

## SQL pack

`isitright.packs.sql.check(...)` and `check_suite(...)` return a `CaseReport` and an
`AuditReport`. Inputs: `engine` (`sqlite`, `postgres`, `duckdb`), exactly one of `database` (a
SQLite file) or `ddl`, the two queries, optional `constraints` (JSON Schema, as a dict or YAML/JSON
file), a trusted `validator`, and `CheckConfig` (seed, attempt and minimization budgets, timeout,
row cap, comparison policy). The source database is never modified. `check` returns `UNSUPPORTED`
for SQLite queries it cannot run and raises `SqlInputError` for unsupported PostgreSQL or DuckDB
queries; a suite turns both into `UNSUPPORTED` cases.

Comparison: multisets unless the reference query has a top-level `ORDER BY` (`auto`), positional
columns (`positional`, `by_name`, `names_and_positions`), floats `exact` or `isclose` (1e-9
relative, 1e-12 absolute). The policy is recorded. Ambiguity (collation, nondeterminism, ties) is
`INCONCLUSIVE` or `UNSUPPORTED`. The suite input is JSONL with `case_id`, `reference_sql`,
`candidate_sql`, optional `question`; other fields are preserved as metadata. Evidence for a
finding includes both results, the difference, the minimized state (`candidate_state`), a
`reproducer_sql` and the mutation path.

Reports written by the CLI or `write_case_report` include `case_report.json`, `case_report.md`,
`counterexample.sql` and `replay.json` (a `ReplayArtifact` with the concrete minimized rows, the
schema DDL and the expected results). Replay (`isitright sql replay REPORT`) rebuilds the schema
and rows on the recorded engine and compares both outputs; report-provided SQL is never executed
as state. `python -m isitright.packs.sql.fixture_replay --report R --fixture F` replays a
hand-edited SQLite fixture under an authorizer that denies `ATTACH`, triggers, extension loading
and other PRAGMAs, with a 30-second deadline and a 10,000-row result cap.

## MCP pack

See [agents](agents.md). A report is one `scenario` case; `extensions.mcp.runs` holds one record
per run (status, exit code, duration, calls, writes, violations, oracle outcome, run directory,
cost and, when the agent wrote a transcript, the stack under test).

## Eval-case export

`EvalCase` (`pack`, `case_id`, `source_finding`, `payload`, `expectation`) is the export format.
SQL: a fixture state, both queries and the expected disagreement; `rerun_eval_case` rebuilds it
and checks the queries still disagree as recorded. MCP: the world, the task, the recorded trace
and the verdict; `rerun_eval_case` replays the trace offline and re-judges it.

## CI policy and exit codes

`--fail-on none|domain-counterexample|any-counterexample` (agents: `none`,
`invariant-violation`, `any-finding`). An emulated finding that no native run verified never fails
CI. Exit codes: `0` completed, `1` internal error or inconclusive, `2` invalid input, `3` the
opt-in policy triggered.
