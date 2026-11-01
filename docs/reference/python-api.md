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
check(*, reference_sql, candidate_sql, engine="sqlite", database=None, ddl=None,
      question=None, case_id=None, constraints=None, constraints_file=None,
      config=None, validator=None, verify_native=None) -> CaseReport
```

| Argument | Notes |
|---|---|
| `engine` | `"sqlite"`, `"postgres"` or `"duckdb"` |
| `database`, `ddl` | Exactly one. A SQLite file path, or a DDL string |
| `constraints`, `constraints_file` | JSON Schema [domain rules](../sql/domain-constraints.md) as a dict, or a YAML or JSON file |
| `config` | A `CheckConfig`. See below |
| `validator` | A trusted `CandidateStateValidator` callback. See [Domain constraints](../sql/domain-constraints.md) |
| `verify_native` | Re-execute DuckDB findings on PostgreSQL. Defaults to on when available |

The source database is never modified. `check` returns an `UNSUPPORTED` report for SQLite queries it
cannot run, and raises `SqlInputError` for unsupported PostgreSQL or DuckDB queries.

### `check_suite`

```python
check_suite(*, cases, engine="sqlite", database=None, ddl=None, constraints=None,
            constraints_file=None, config=None, validator=None, verify_native=None) -> AuditReport
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

### Reading the result

`CaseReport` and `AuditReport` are Pydantic models matching the [report schema](report.md):
`report.divergence_status`, `report.headline`, `report.validity.tiers`, `report.findings`,
`report.search.rejected`, `report.unused_rules`.

## Agent pack

```python
from isitright.packs.mcp.model import (
    McpScenario, ToolDef, ScenarioOracle, Invariant, Layout, FixedWorld, Expectation,
    ToolCallError, load_scenario,
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
