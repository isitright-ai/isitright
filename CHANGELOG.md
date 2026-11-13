# Changelog

All notable changes are documented here. The project follows semantic versioning.
Versions before 1.0 may break the API, the CLI and the report schema.

## 0.8.0 - Research agents

Agents that answer a question by searching a frozen corpus and citing documents are audited by
planting, removing, editing, superseding and retracting documents. See `docs/research/index.md`.
Everything reported about stand-in agents describes the stand-ins; the release was built and tested
offline, without a model, an account or a real research agent.

### Added

- **`isitright research check | replay | export`.** Subjects: a built-in stand-in agent written by
  Claude, an agent as code (`--agent`), an agent command that uses the MCP server
  (`--agent-command`), or a recorded run replayed frozen (`--recorded-run`). Live subjects get the
  0.5 budgets, repeated runs, the paired sequential test and noise-tolerant minimization; `--screen`
  replays the baseline trace first and skips worlds that cannot matter.
- **The corpus as a world.** A `documents` collection in the core state (stable id, typed
  metadata, opaque text); validity rules over metadata (supersede dates, reference cycles, a
  cutoff, visible retractions); `OBSERVABLE` computed per world from retrieval, so a change no
  query can retrieve is `UNOBSERVABLE`.
- **Frozen retrieval and two tools.** A BM25 whose statistics come from the original corpus and do
  not move when a world mutates; `search` and `open` only, in process or as a stdio MCP server
  (`python -m isitright.packs.research.serve`, needs the `mcp` extra); anything else is refused.
- **Mutators.** `plant`, `contradict` (both tie orders), `supersede`, `retract`, `remove`,
  `duplicate`, `out_of_scope`, and the response edits `reorder` and `snippets`, with a constructive
  or relational oracle each. A reference procedure over the corpus computes the expected behavior,
  so a world where the right answer changes is a control and one where it stays is a trap. An
  answer must be one the expectation recognizes: a stated conflict never rescues an unrelated
  answer. Number and date answers must be exact (one value, no negation); anything else is
  `CANNOT_JUDGE`.
- **Behavior labels that respect exposure.** `FOLLOWED` (the agent was shown the added claim and
  adopted it), `REJECTED` (shown, not adopted), `NOT_EXPOSED` (the document appeared as an id and
  title only), `MATCHED_WITHOUT_EXPOSURE`, `EXPOSURE_UNKNOWN` (a snippet cut before the claim) and
  `NOT_RETRIEVED`. A snippet shows the claim only if it contains the mutation's own sentence.
  Beneath the labels, per added document: `appeared`, `claim_exposed`, `adopted`, `cited`.
- **Citation checks.** L0 (the cited id exists) and L1 (the quote occurs in the document); L2
  (support) is not judged. Reported beside them, never changing the level: claim coverage,
  retrieval provenance (the id appeared in the trace) and `cited_quote_exposed` (the cited sentence
  appeared in tool output; a valid citation does not show the agent was shown it).
- **Reporting.** A flip table per mutator (worlds, answers changed, expectations not met, judged
  and unjudged runs, the observations above); `CANNOT_JUDGE` runs counted per mutator with
  truncated examples and every answer in `cannot-judge.jsonl` beside the report; for a recorded
  run, `frozen_fidelity` (how closely the simulated retrieval reproduced the recorded results) and
  a note of which conclusions depend on it. Findings carry the trust label of the gold answer.
- **Stand-in agents** written by Claude (careful, credulous, snippet reader, non-retrieving,
  refusing, skeptic, ambiguous, mixed), with declared behaviors; every result says which subject
  produced it.
- **Core.** A text-span entry in `diff_states` for long text values (`text_span`). The core's
  search, minimizer and replay run unchanged on documents and on a tree of text files.
- **Examples.** `examples/research/`: a constructed corpus and task (proposed fixtures), a scripted
  command agent, and the BrowseComp-Plus demo scripts.

### Changed (breaking)

- Report schema `0.8` replaces `0.6` (`schemas/report-0.8.schema.json`; the 0.6 file is removed).
  Additive: `findings[].mode` may be `frozen_trace`. Reports written as 0.4, 0.5 and 0.6 still load.
  Replay artifacts of version 0.4 to 0.6 still load; new ones are written as 0.8.
- `isitright --version` reports 0.8.0.

## 0.7.0 - Warehouse dialects

BigQuery and Presto/Trino queries are audited from table definitions alone, without moving data.
The search runs on DuckDB; findings are confirmed on your own engine with the state written into
the query text. See `docs/sql/warehouses.md`.

### Added

- **Dialects.** `--dialect sqlite|postgres|bigquery|presto|trino` (the SQL the queries are written
  in) apart from `--engine` (where states run). `--engine` alone keeps its 0.6 meaning.
- **Schema import** for BigQuery DDL (as `INFORMATION_SCHEMA` and Spider ship it), Presto/Trino
  `SHOW CREATE TABLE` and Hive DDL: qualified names, optional and unenforced keys, partitions as
  columns, column descriptions, `TIME` columns.
- **Nested types** (`ARRAY`, `STRUCT`, `MAP`/`ROW`): generation scoped to the columns the queries
  read, a nested mutation family, validity per dialect (BigQuery stored arrays hold no NULL array
  or NULL element), minimization inside arrays, comparison of nested results.
- **Query templates** (`--param`, `params` in a suite case) for `<NAME>` and `{{ NAME }}`.
- **Comparison options**: `contained` columns, `--reference-columns`, `--column-vectors`,
  `--null-as-zero`, and `--wall-time`.
- **Constraints file**: `x-unique` rules. A finding that needs equal values in a column with no
  declared key or unique rule says so in `validity.notes`.
- **Fidelity fixtures** for both dialects and exact translations for the divergences found
  (`WITH OFFSET`, `ARRAY_AGG ... IGNORE NULLS`, array subscripts, division by zero, `DAYOFWEEK`,
  `DATE_TRUNC`, session time zone, Presto integer division). SQLGlot's "unsupported" warnings are
  errors.
- **Native confirmation hosts** (`NATIVE_INLINE`): BigQuery (dry run, bytes cap, labels), Trino, and
  a function you supply (`--confirm connection --connection module:function --trust-code`). Every
  host refuses text that still names a real table. The `bigquery` and `trino` extras are optional.
- **Spider 2.0-lite BigQuery demo** under `examples/sql/spider2/`.

### Changed

- `check` and `check_suite` take `dialect`, `params` and `confirm`; `engine` defaults to the
  dialect's engine. `SqlValue` now includes lists and mappings (nested values).
- `core/jsonpaths.py` reads a JSON Schema `type` given as a list (nullable leaves).
- No breaking change to the SQLite, PostgreSQL or DuckDB invocations. The report schema stays 0.6.

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

## 0.6.0 - The data-analysis pack

0.6 adds a third domain on the same core: agents that write and run Python over data files. A new
domain mostly reuses the core; `docs/data.md` describes what it adds.

### Added

- **Data-analysis pack** (`isitright.packs.data`, CLI `isitright data`, extra `data`). Tables are
  collections and rows are entities. Recorded programs (the code an agent executed) are replayed on
  generated worlds (**frozen**), and frozen candidates are confirmed with the agent itself
  (**live**, under the 0.5 budgets, stopping rules and sequential test). Findings are minimized,
  replayable and exportable as eval cases (dataset, question, gold program, expected answer).
- **Host** that runs programs in a separate process with a scrubbed environment, a timeout and a
  memory limit, behind `--trust-code`. It is not a sandbox; the documentation says what it does and
  does not protect against. On Windows the runner puts itself in a Job Object with the limit, so the
  limit also reaches environments whose `python.exe` is a launcher.
- **Comparators** with a recorded policy and tolerance basis: `NumericComparator` and
  `TextComparator` in the core; named answers and frames in the pack.
- **Adapters** for PandasAI and smolagents `CodeAgent` behind one method, tested against fakes, and
  a subprocess boundary for agent code.
- Constraints from a **pandera** schema (extra `data-schema`); Parquet input and output (extra
  `parquet`).
- **Core:** `column`, `literal` and `tolerance` hint kinds and `harvested:question` provenance;
  `core/selection.py` (ranking, coverage order, stopping rules, now shared with the MCP pack).
- **Report schema 0.6:** `findings[].mode` and `findings[].live` separate a frozen program's finding
  from the agent's own runs; `fidelity.verified_on` can be `LIVE_AGENT`.
- `docs/write-your-own-host.md` and `examples/hosts/table_cli/`: a host written outside the pack
  using only core interfaces (experimental).
- `isitright data check --resume` and `--cache DIR`: finished programs are saved as they complete
  and finished host runs are kept on disk, so an interrupted audit continues without repeating them.
- `isitright data audit --env-file FILE` reads the `--pass-env` variables (an API key) from a
  dotenv-style file; both paid commands refuse to start when a named variable is not set. The
  capture script takes the same option plus `--max-money`, which stops before the next run once the
  cost the agent reports reaches the cap, and writes its recordings after every run. `.gitignore`
  now covers `.env`, `.env.*` and `*.env`.
- A recorded program whose final answer is a literal the agent typed (every `final_answer(...)` call
  has only constant arguments) is `UNSUPPORTED` for frozen replay: it would print the same answer on
  every world. Found with the first real agent's programs.
- Found by running a real agent (smolagents `CodeAgent` with an OpenAI model) through capture, frozen
  audit and live audit: steps that raised an error are wrapped in `try / except` when an agent's steps
  are joined, so the replay does what the agent did; the default imports include `pandas.*`,
  `numpy.*` and `scipy.*` (smolagents rejects submodules otherwise); the `stop` parameter is dropped
  for OpenAI models; repeated blocks of `@name[value]` answers compare as groups without order; quote
  characters around a name or list item are ignored; the numeric policy for a stated number of
  decimals allows floating-point noise on top of one unit in the last place; a live world whose
  reference answer is NaN is not judged; the frozen step of `data audit` uses `--attempts`; the
  Windows memory limit is applied by the runner itself.

### Changed (breaking)

- Report schema `0.6` replaces `0.5` (`schemas/report-0.6.schema.json`). `0.4` and `0.5` reports still
  load. The replay artifact version is `0.6` (older ones still load).
- The `Comparator` protocol has a `describe()` method.
- The SQL pack no longer registers the `column` and `literal` hint kinds; the core does.
- `isitright.packs.mcp.screening` and `isitright.packs.mcp.generate` re-export the ranking and
  stopping-rule code that now lives in `isitright.core.selection`.
- Static typing is checked against Python 3.12 (numpy's stubs need it). The runtime floor is still 3.11.

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
