# Changelog

All notable changes are documented here. The project follows semantic versioning.
Versions before 1.0 may break the API, the CLI and the report schema.

## 0.4.0.dev0 (unreleased) - A core for auditing agent evals

0.4 replaces the internals of 0.1 and 0.2 with a core that both packs sit on, and adds the MCP
agent pack. Earlier releases (0.1.x, 0.2.0) are on PyPI; the breaking changes below are relative to
them.

### Added

- `isitright.core`: worlds as serializable states with atoms and fingerprints; an entity model
  (collections, typed fields, keys, references, dependent clusters, embedded entities); a
  constraint language that checks and guides generation (`Range`, `OneOf`, `NotNull`, `Unique`,
  `FunctionalDependency`, `Aggregate`, row expressions; Python predicates are check-only);
  validity tiers; mutations with three targets (state, response, timing); sixteen generic
  families, composed to depth two with a priority order; declared hints with provenance (`lookup`,
  `ordering`, `gate`, `scope`, `threshold`, plus registered kinds); search with budgets in
  attempts, runs, time and money; stochastic evaluation (baselines, repeated runs, counts, an exact
  McNemar test and a minimum of 8 paired runs before any rate claim); minimization (ddmin over
  atoms, revert toward the base world, mutation-path minimization); replay artifacts; one report
  model; eval-case export; suite ranking; the CI policy.
- `isitright.packs.sql`: one audit for SQLite (database file or DDL), PostgreSQL (native, from
  DDL) and DuckDB (emulated). Counterexamples carry the mutation path, the hints behind it and
  `replay.json`; `isitright sql replay` and `isitright sql export`.
- `isitright.packs.mcp`: declare a scenario (entity schema, constraints, tools, service
  parameters, hints, oracle); worlds are generated; roles (control or trap) are computed by the
  scenario's reference procedure; worlds the oracle cannot judge are `CANNOT_JUDGE`; changes no
  read tool shows are flagged unobservable; response and timing mutations run as host middleware;
  `isitright agents run|replay|export`. The shop support desk is declared this way and
  generates the classified worlds (acceptance report: project notes, not in the repo).
- Hypothesis is a runtime dependency: edge values (zero, negative, huge or tiny numbers; empty,
  padded or non-ASCII text) inside the declared value domain.
- Report schema `0.4` (`schemas/report-0.4.schema.json`).

### Changed (breaking)

- CLI: `isitright check` is `isitright sql check`, `suite` is `sql suite`, `postgres check|suite|
  replay` are `sql check|suite|replay --engine postgres|duckdb`; the PostgreSQL commands' output
  directory rule (must not exist) now applies to non-SQLite engines only. `agents run` defaults
  to `--worlds generated` and `--trials 4`; `agents` has `--world`, `--max-worlds` (default 50, selected for coverage), `--max-runs`, `--max-seconds`,
  `--max-money` (refused if the agent does not report a cost for each run), `--worlds fixed|generated|all`.
- SQL search budget: `max_attempts` defaults to 500 (was 100). Attempts run locally against the
  database engine and cost no money; a search stops earlier when it runs out of candidates (SQLite
  about 0.2 s, DuckDB about 17 s, PostgreSQL about 40 s when all 500 are used).
- Python API: `check`, `check_suite` take an `engine` and either `database` or `ddl` and return
  `CaseReport` and `AuditReport` models (`divergence_status`, `validity` tiers, `findings`) instead
  of `CaseResult`, `SuiteResult` and the PostgreSQL dicts. `check_postgres`,
  `check_postgres_suite` and `replay_postgres` are gone.
- Status and validity names: `AGREEMENT_ON_TESTED_STATES` is `NOT_FOUND_WITHIN_BUDGET`;
  `SCHEMA_VALID_ONLY` is the `STRUCTURAL` tier; `DOMAIN_VALIDATED` is a tier. Mutation families
  are the generic ones (`null` and `aggregation` are `missing`; `join` is a parent without a
  child through `duplicate`, `empty`, `dangling` or `missing`; `filtering` is `boundary`).
- Replay reads the concrete minimized rows from the report (`replay.json`); report-provided SQL is
  never parsed as state. The hand-readable `counterexample.sql` can still be replayed with
  `python -m isitright.packs.sql.fixture_replay`.
- Agents: scenarios are declared (`isitright.packs.mcp.model.McpScenario`) instead of built from
  hand-written `Scenario` and `World` objects; the old classes are removed. The hand-written shop
  and booking worlds are `FixedWorld`s. `isitright.mcphost` moved to `isitright.packs.mcp`.
  Reports use schema 0.4.
- Removed: schemas 0.1 and 0.2 and their exporters; the SQLite-specific generation, search and
  minimization modules; the `writable` SQLite sandbox.

### Fixed

- Reproduction of cyclic deferred foreign keys in SQLite no longer depends on statement order.
