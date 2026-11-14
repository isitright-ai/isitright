# Python API

The CLI is a thin layer over these. The top-level package exports the SQL entry points. Everything
under `isitright.core` is the extension API, which is **experimental** until a pack is written by
someone other than its author.

## SQL pack

```python
from isitright import check, check_suite, CheckConfig, SuiteCase, SqlInputError
```

### `check`

```python
check(*, reference_sql, candidate_sql, engine=None, dialect=None, database=None, ddl=None,
      question=None, case_id=None, constraints=None, constraints_file=None,
      config=None, validator=None, verify_native=None, params=None, confirm=None,
      gold_trusted=None, gold_trust_basis=None) -> CaseReport
```

| Argument | Notes |
|---|---|
| `engine` | `"sqlite"`, `"postgres"` or `"duckdb"`: where states run. Defaults to the dialect's engine (SQLite when neither is given) |
| `dialect` | `"sqlite"`, `"postgres"`, `"bigquery"`, `"presto"` or `"trino"`: the SQL the queries are written in. BigQuery, Presto and Trino need `ddl` (table definitions), and the search runs on DuckDB. See [BigQuery and Presto/Trino](../sql/warehouses.md) |
| `params` | A dict that fills `<NAME>` and `{{ NAME }}` in the queries ([query templates](../sql/warehouses.md#query-templates)) |
| `confirm` | A native host that re-runs findings on your engine with the state written into the query text: `BigQueryHost`, `TrinoHost` or `ConnectionHost` from `isitright.packs.sql.native`. Each refuses text that still names a real table. `BigQueryHost` and `TrinoHost` need the `bigquery` or `trino` extra |
| `gold_trusted`, `gold_trust_basis` | Whether you know the reference is right, and how you decided. See [Audit a suite](../sql/audit-a-suite.md) |
| `database`, `ddl` | Exactly one. A SQLite file path, or a DDL string |
| `constraints`, `constraints_file` | JSON Schema [domain rules](../sql/domain-constraints.md) as a dict, or a YAML or JSON file |
| `config` | A `CheckConfig`. See below |
| `validator` | A trusted `CandidateStateValidator` callback. See [Domain constraints](../sql/domain-constraints.md) |
| `verify_native` | Re-execute DuckDB findings on PostgreSQL. Defaults to on when available |

The source database is never modified. `check` returns an `UNSUPPORTED` report for SQLite queries it
cannot run, and raises `SqlInputError` for unsupported PostgreSQL or DuckDB queries.

### `check_suite`

```python
check_suite(*, cases, engine=None, dialect=None, database=None, ddl=None, constraints=None,
            constraints_file=None, config=None, validator=None, verify_native=None,
            params=None, confirm=None) -> AuditReport
```

`cases` is a path to a JSONL file or a list of `SuiteCase`. A suite turns both unsupported-query
outcomes into `UNSUPPORTED` cases and isolates per-case failures.

```python
suite = [SuiteCase(case_id="q1", reference_sql="SELECT ...", candidate_sql="SELECT ...")]
report = check_suite(cases=suite, database="shop.sqlite", config=CheckConfig(max_attempts=200))
```

### `CheckConfig`

| Field | Default |
|---|---|
| `seed` | `0` |
| `max_attempts` | `500` |
| `timeout_seconds` | `30.0` |
| `max_result_rows` | `10000` |
| `minimization_max_attempts` | `500` |
| `column_policy` | `ColumnComparisonPolicy.POSITIONAL` |
| `ordering_policy` | `OrderingPolicy.AUTO` |
| `float_mode` | `FloatComparisonMode.ISCLOSE` |
| `float_relative_tolerance`, `float_absolute_tolerance` | `1e-9`, `1e-12` |
| `column_vectors` | `False`. With unordered comparison, compare each column as its own sorted vector |
| `null_as_zero` | `False`. Count NULL as 0 before comparing |
| `reference_columns` | `None`. Compare only these reference columns (0-based) |
| `wall_time_seconds` | `None`. Stop the search after this long; the report says the time cap stopped it |
| `nested_scope` | `"path"` (new in 0.9). `"column"` generates and mutates every field of a nested column a query reads, as in 0.7: see [BigQuery and Presto/Trino](../sql/warehouses.md#nested-types) |

`column_policy` also accepts the `contained` policy. The last four fields and `contained` exist for benchmark-style comparison: see [BigQuery and Presto/Trino](../sql/warehouses.md#comparing-the-way-a-benchmark-does).

### Reading the result

`CaseReport` and `AuditReport` are Pydantic models matching the [report schema](report.md):
`report.divergence_status`, `report.headline`, `report.validity.tiers`, `report.findings`,
`report.search.rejected`, `report.unused_rules`.

## Agent pack

```python
from isitright.packs.mcp.model import (
    McpScenario,
    ToolDef,
    ScenarioOracle,
    Invariant,
    Layout,
    FixedWorld,
    Expectation,
    ToolCallError,
    load_scenario,
)
from isitright.core.entities import EntitySchema, CollectionSpec, FieldSpec, RefSpec
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.spec import WorldSpec, ToolSpec, ParamSpec, Operation
```

| Class | Purpose |
|---|---|
| `McpScenario(id, task, spec, tools, base, layout, oracle, hints, fixed_worlds, fidelity, external)` | The [scenario](../agents/write-a-scenario.md) |
| `ToolDef(name, description, input_schema, handler, writes=False)` | A tool with its simulated handler |
| `ScenarioOracle(name, invariants, reference, normalize, normalize_call, ignored_writes, judgeable, assumptions, description)` | The [oracle](../concepts/oracles-and-roles.md) |
| `Invariant(name, description, check)` | `check(before, after, trace) -> list[str]` |
| `Layout(keyed, listed, scalars, block, defaults)` | Maps the service state to the entity state |
| `FixedWorld(id, role, description, build, validate, expectation, interferences)` | A hand-written regression world |
| `Expectation(name, description, met)` | What is right in one fixed world |

`load_scenario("file.py:SCENARIO")` imports and returns a scenario. It executes the referenced code:
trusted use only. See [Write a scenario](../agents/write-a-scenario.md).

Running an audit from Python is done through the CLI (`isitright agents run`), which owns the
runner, the report and the output directory.

## Data pack

Needs the `data` extra. Importing `isitright.packs.data` does not import pandas.

```python
from pathlib import Path
from isitright.packs.data.task import load_task
from isitright.packs.data.audit import DataAudit, AuditConfig
from isitright.packs.data.programs import load_programs
from isitright.packs.data.live import run_live, LiveConfig
```

| Name | Notes |
|---|---|
| `load_task(directory)` | Reads a [task directory](../data.md) into a `DataTask` |
| `DataAudit(task, config)` | A context manager. Prepares the task once and checks recorded programs against it. `AuditConfig` has `seed`, `attempts`, `depth`, `timeout_seconds`, `memory_mb`, `trust_code` (must be `True` to run any program), `cache_dir` (resume an interrupted audit) and `parallel` |
| `DataAudit.check_frozen(program)` | Replays one `RecordedProgram` on generated worlds and returns a `CaseReport` |
| `load_programs(path)` | Reads recorded programs from a JSONL file |
| `AnswerPolicy.for_question(text)`, `DataComparator` | The comparison policy of a task: tolerance and its basis, `ulps` (a margin of exactly that many units in the last place, new in 0.9), `per_answer` decimals (new in 0.9). `NumericComparator(abs_tol, rel_tol, basis, ulps=0)` is the core class |
| `memory_enforcement()`, `DataHost.describe()["memory_enforcement"]` | How the memory limit is enforced here: `job_object`, `rss_watchdog`, `address_space` or `none` (new in 0.9) |
| `run_live(audit, agent, program=..., config=..., budget=...)` | Runs a `DataAgent` (`name`, `model`, `solve(question, directory)`) on the ranked worlds, under the budgets and sequential test of `agents run`. `LiveConfig` has the trial and world limits |

Programs run in a separate, limited process that is not a sandbox: see [Data analysis agents](../data.md).

## Research pack

The research pack is driven from the CLI (`isitright research`). Its modules are `isitright.packs.research`; the surface is experimental. See [Research agents](../research/index.md). What 0.9 adds for use from Python:

| Name (module) | Notes |
|---|---|
| `Retriever`, `FrozenIndex`, `EmbeddingIndex(embed, documents)`, `HybridIndex(first, second)`, `hashed_embedding(text)`, `build_index(stats, documents)`, `sentence_transformers_embedder(model)` (`retrieval`) | The retrievers behind the tools. `FrozenStats.from_documents(documents, retriever)` names which one a world uses (`bm25`, `hashed-dense`, `hybrid`) |
| `SupportJudge`, `JudgeLabel`, `Validation`, `QuoteContainsAnswer`, `check_support(report, documents, judge, kind)` (`support`) | L2 behind a judge interface; no model judge is shipped |
| `build_app(host, run_dir, token)`, `main` (`http_server`) | The streamable-HTTP MCP server with a bearer token |
| `RecordedRun.own_retrieval` (`runs`) | The searches an agent ran on its own retriever, for `own_retriever_fidelity` |


## Evidence and eval cases

```python
from isitright.core.evidence import AuditReport, CaseReport, EvalCase
from isitright.packs.sql.replaying import export_eval_cases, rerun_eval_case
```

## Core extension API (experimental)

| Protocol | Method | Module |
|---|---|---|
| `Mutator` | `family`, `target`, `consumes`, `propose(spec, world, hints)` | `isitright.core.mutations` |
| `Host` | `fidelity`, `prepare(spec, world)` (a context manager) | `isitright.core.hosts` |
| `Subject` | `kind`, `run(handle, task)` | `isitright.core.subjects` |
| `Oracle` | `kind`, `name`, `description`, `judge(task, before, run)` | `isitright.core.oracles` |
| `Constraint` kinds | `Range`, `OneOf`, `NotNull`, `Unique`, `FunctionalDependency`, `Aggregate`, `RowExpr`, `JsonSum`, `Pattern`; `PythonConstraint` is check-only | `isitright.core.constraints` |
| `register_hint_kind` | Add a [hint](../concepts/hints.md) kind | `isitright.core.hints` |
| `search` | `search(spec, base, hints, mutators, evaluate, *, budget, seed=0, depth=2, ...)` | `isitright.core.search` |

See [Write a mutator or host](../guides/extending.md).
