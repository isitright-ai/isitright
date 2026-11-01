# Changelog

All notable changes are documented here. The project follows semantic versioning.
Versions before 1.0 may break the API, the CLI and the report schema.

## 0.5.1 - 2026-11-01

### Added

- `agents run --baseline-trials` (a baseline run count apart from `--trials`), a progress line
  while worlds are generated, `ScenarioOracle.ignored_writes`, `agents order` (compare world
  orderings offline from a finished run), and `sql slice` (a small database holding the rows the
  reference query used, with `isitright.packs.sql.slicing`).
- The runner records a simulated user's usage (`user_usage` in `transcript.json`) apart from the
  agent's and counts it in `money`. The tau2 example reports it, and ends a conversation the user
  stopped right after the agent's question as a run that did not complete (exit code 3;
  `--accept-unanswered-stop` keeps the old behavior). Its adapter passes `max_turns` (default 30,
  `ISITRIGHT_AGENT_MAX_TURNS`) instead of the SDK's 10.

### Changed

- A `threshold` hint can declare `inclusive` and `holds`. A generated world exactly on a cut-off
  that is not declared is `CANNOT_JUDGE`; one that is declared is judged only if the reference
  agrees with the declaration.
- **Neighbor values of a boundary** are written like the value: a datetime without a zone no
  longer gets a `Z` (a scenario comparing it with a naive clock raised `TypeError`, which made
  every ±1 s world `CANNOT_JUDGE`), and a date moves by a day.
- **Generated world ids** are `g<hash>_<families>` and no longer depend on the order of the
  search, so ids from older reports do not match.
- SQL literal hints pair a literal only with the columns the query compares it with, so a format
  string such as the first argument of `STRFTIME` is no longer tried as a value of a date column.
- Applying edits to a state copies only the rows it changes, which makes a proposal on a large
  database much cheaper.
- Agents start with one numeric-library thread each unless the environment says otherwise.
- SQLite foreign-key failures name the tables and the number of rows involved.
- The airline example judges certificates and flight changes with two policy invariants
  (`policy_checks.py`) instead of comparing them with the reference, and leaves the world exactly
  on the 24-hour cut-off undeclared, so it is `CANNOT_JUDGE`.

### Fixed

- `agents run --max-runs 1` (any budget spent before a generated world ran) no longer fails the
  report validation; it reports `NOT_FOUND_WITHIN_BUDGET` and the budget that ended the run.
- A baseline run that did not complete is skipped when pairing instead of ending the world's runs
  with the sequential test undecided.

## 0.5.0 - Evidence at scale

0.5 makes live-agent audits affordable and their evidence defensible: it chooses which worlds to
run, stops on rules instead of counts, tests sequentially, minimizes through noise, verifies
emulated SQL findings natively, and closes the 0.4 gaps.

### Added

- **Choosing which worlds to run.** Screening without the agent replays the baseline trace on each
  candidate world and runs the oracle (`WRONG_IF_UNCHANGED`, `STALE`, `RIGHT_IF_UNCHANGED`,
  `UNSCREENABLE`); ranking (`--ranking diverse|screening|coverage|random`, default `diverse`);
  stopping rules for a stratum and for the run (`--stratum-patience`, `--run-patience`). Worlds not
  run are listed as `NOT_RUN` with the reason. A stopped stratum is reported as "no finding in n of
  m worlds".
- **Sequential testing** of paired baseline and perturbed runs (a sequential probability ratio test
  on discordant pairs, false claims at most alpha over all looks; `--max-trials`,
  `--sequential/--no-sequential`) and **noise-tolerant minimization** of a finding's mutation path
  (`--minimize`), with the test, looks, boundaries and error bounds in the report.
- **A family that edits inside JSON values** where a scope is declared (`FieldSpec.shape` or a
  `json_path` hint such as `orders.items[*].price`); the `JsonSum` constraint reads a path inside
  JSON; an unconstrained JSON edit is `STRUCTURAL` only and says so.
- **Pattern strings**: JSON Schema `pattern` drives generation (`Pattern` constraint,
  `core.values.pattern_value`); unsupported constructs are reported in `search.notes`.
- **Native verification of emulated SQL findings**: a DuckDB divergence is re-executed on
  PostgreSQL (`--verify-native`, on by default when the extra is installed); `verified_on` is
  populated, a divergence that fails verification is an emulation artifact and is not a
  counterexample; integer division is translated; `CHECK` constraints are accepted.
- **LLM-proposed hints** (plumbing only): `HintProposer`, `agents hints propose|confirm`,
  `agents run --hints`; hints labeled `proposed` prioritize and never grant a validity tier.
- **External servers**: a third-party MCP server whose state lives in a JSON-lines file or a
  SQLite database can be the service (`ExternalServer`, `JsonLinesFile`, `SqliteFile`, a proxy
  host with final-state export); an example scenario over the Memory reference server.
- Examples: an airline scenario that serves tau2's own tools on generated worlds with a policy-based oracle (`examples/agents/airline`); the OpenAI Agents SDK adapter behind a narrow interface (`examples/agents/tau2_openai`),
  the tau2 airline entity model and hints (`examples/agents/airline`), a hint proposer adapter.
- `agents run` prints progress on stderr: one marker per agent run (`.` as expected, `V` invariant
  violated, `N` expected behavior not met, `?` not judged, `E` run did not complete), a line per
  world, and a summary with the run count and elapsed time.
- Report schema `0.5` (`schemas/report-0.5.schema.json`); 0.4 reports still load.

### Changed (breaking)

- Report schema 0.5 replaces 0.4 (`schemas/report-0.4.schema.json` is removed); new fields are
  optional, so 0.4 reports can still be replayed and exported.
- `agents run` ranks worlds by screening (default `diverse`) instead of coverage, and records
  worlds it did not run as `NOT_RUN` (they used to appear with zero counts or not at all). The
  case-level `stability` of an agent report is counts only; a rate claim is per world.
- A DuckDB finding that PostgreSQL confirms may now fail CI (`verified_on` is set); one it does
  not confirm is excluded as an emulation artifact. Use `--no-verify-native` for the 0.4 behavior.
- `SELECT 5 / 2` on the emulating engine is now integer division, as in PostgreSQL.
- A generated world whose JSON field was edited without a rule over its content has the
  `STRUCTURAL` tier only.

## 0.4.0 - A core for auditing agent evals

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
