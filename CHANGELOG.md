# Changelog

All notable changes are documented here. The project follows semantic versioning.
Versions before 1.0 may break the API, the CLI and the report schema.

## 0.9.0 - Unreleased

Evidence integrity. 0.9.0 moves the report schema to 0.9. Changes are listed by package.

### N1: one run loop in the core (breaking: cost and report fields)

- **One loop runs every subject.** `isitright.core.stochastic.SubjectRunner` is the only code that
  executes a subject (an agent command, a data agent, a research stand-in or agent). It checks the
  budget before every call (baseline, search, minimization and confirmation alike), records the
  cost of every run (an errored run included), counts the calls and derives a distinct seed for
  every call from the audit's base seed and the call's index, so no seed repeats across worlds,
  minimization repeats or confirmation runs. The agents, data and research packs had one loop each
  and now call it; their copies are removed, together with `run_repeated` and
  `run_paired_with_baseline`. A test fails if code outside the runner calls a subject's `execute`.
- **A fresh baseline run for every pair, in all three packs.** A pair is one run of the world and
  one run of the baseline made for that pair. No baseline outcome is reused, cycled or assumed.
  The agents pack reused the baseline runs made before the search for the first pairs; the
  research pack stopped at the baseline runs it had (0.8.1) after assuming a pass beyond them
  (0.8.0); the data pack stopped likewise (0.8.1) after cycling three outcomes (0.8.0).
- **A run that errored or could not be judged forms no pair.** The sequential record counts the
  world runs and baseline runs that were made and the runs left out (`world_runs`,
  `baseline_runs`, `excluded_errored`, `excluded_unjudged`). When two runs in a row form no pair
  the world is given up, so an agent that never completes costs a few runs.
- **Cost.** A sequential test now costs two runs per pair. A world that runs to the limit costs
  40 runs at the default 20 pairs. (N1 charged `2 x minimum pairs` for a world with no failure; N2
  below makes that world cost only its first runs.) The baseline runs made before
  the search are no longer part of the pairs. The pair limit is 20 in all three packs: the data
  pack's `--max-trials` (and `LiveConfig.max_trials`) rises from 10, and research
  (`AuditConfig.max_pairs`) and agents (`--max-trials`) from 16. In a simulation of a rise from
  10% to 70%, 10 pairs found it in about 40% of tests and 16 in about 85%; 20 pairs find it in
  about 94% of tests with a minimum of 4 pairs (research, agents) and about 91% with 3 (data).
  The minimum pair counts are unchanged.
- **Research:** a budget that allows no run at all (`--max-runs 0`) is refused with an input error
  instead of making one baseline run past the budget. The research pack's pair limit is
  `AuditConfig.max_pairs` (default 20); the baseline run count (`runs`) no longer caps it.
- **Data:** the report's `inputs.baseline_runs` still counts the runs made before the search; the
  fresh runs made for the pairs are in `inputs.paired_baseline_runs`.
- **Agents:** each run in `extensions.mcp.runs` carries its `seed`. The seed is derived and
  recorded; it is not passed to the agent command (an agent that takes a seed is a later change).
- **Report schema 0.9.** `stability.sequential` gains `world_runs`, `baseline_runs`,
  `excluded_errored` and `excluded_unjudged` (default 0). Reports in schema 0.4 to 0.8 still load,
  and `replay` and `export` read them.
- **Per finding.** `stability.baseline` counts the baseline runs made for that world's pairs
  (unusable ones included), in all three packs; the runs made before the search are reported
  apart. A research finding whose paired test ended undecided (budget spent or failed pairing
  attempts) no longer falls back to the fixed-sample comparison by run index, which could give a
  rate claim the sequential test never made: it gives counts only.
- **Giving a world up.** After two failed attempts in a row to form a pair (a world run that was
  unusable, or a usable one whose baseline run was not), the world's test ends with counts only;
  a valid pair resets the count.
- **Budget stop reason.** A run refused after the search reports the limit that refused it (runs,
  money or time), not an earlier attempts limit.
- **Tests.** Seeded null simulations through each pack's audit path (equal failure rates of 30%
  and 50%: at most 5% of worlds get a rate increase, plus three standard errors) and power runs
  (10% against 70%: at least 80%, minus three standard errors). The default suite runs a small
  number of audits; `pytest -m statistical` runs the full size.

### N2: finding grades (breaking: statuses, `--fail-on`, report fields)

- **Two grades.** A live-agent finding (agents, data live, research with a stochastic agent) has an
  `evidence_grade`. `RATE_INCREASE`: a paired sequential test crossed its upper boundary, so it
  decided the world fails more often than the baseline. `OBSERVED_FAILURE`: a judged run failed on a
  mutated world that ran and was not found invalid, and no test decided a higher rate. Before, one failed run in a world was a
  counterexample, whatever the baseline did: an agent that fails 5% of its runs at random showed one
  in about half of the audits of a few worlds. Findings of frozen programs and recorded reports,
  deterministic subjects and SQL have no grade (`null`) and keep `COUNTEREXAMPLE_FOUND`.
- **A weaker case status.** `OBSERVED_FAILURE` joins `COUNTEREXAMPLE_FOUND`, `NOT_FOUND_WITHIN_BUDGET`,
  `INCONCLUSIVE` and `UNSUPPORTED`. `COUNTEREXAMPLE_FOUND` now holds only when some finding is not an
  observed failure; `--no-sequential` runs make no pairs, so all their findings are observations and
  a fixed-sample rate claim by run index is no longer printed. The report model enforces this. The
  headline of an observed failure begins "Observed disagreement" and says no paired test decided a
  higher rate.
- **Observed failures are shown.** The console summary, `report.md` (an "Observed failures" section
  next to "Rate increases") and `report.json` (`findings[].observation`) give failures out of
  judged runs with errored and unjudged runs beside them (not in the denominator), a 95% Wilson
  interval, the same for the baseline runs made for the world's pairs, the concrete world diff and a
  replay command, whatever the paired test said.
- **The report says how many worlds were tested** (`multiplicity`): that the per-world decisions are
  not corrected for it, and a nominal upper bound on the false rate-increase claims expected under
  no effect (worlds tested x 0.05; not a measured rate, no family-wise guarantee) and of worlds with an observed failure if
  every world failed at the baseline's rate.
- **CI.** `--fail-on` gains `rate-increase` and `observed-failure` for `agents run` and the live
  research modes. `any-finding`, `invariant-violation` and `any-counterexample` now trip only on a
  rate increase (an observed failure no longer does); `observed-failure` also trips on observations.
  The data pack's live audit takes `--fail-on none|rate-increase|observed-failure` (the broader
  cross-pack vocabulary is N10). The default of every `--fail-on` stays `none`: a rate-based gate is
  opt-in.
- **Export.** Findings graded `OBSERVED_FAILURE` are exported on request: `agents export` and
  `data export` take `--include-observed`; `research check` writes their eval case only with
  `--export-observed` (`research export --include-observed` writes it later).
- **Extra pairs only for worlds that failed.** A world is run `--trials` times (data
  `--baseline-runs`, research `--runs`) first; only one with a failed run goes on to the paired test,
  whose runs are new. A world with no failure costs those runs and no baseline run. The first runs
  take no part in the test, so choosing a world by its failure does not bias it. `stability.world`
  counts all runs of the world; `stability.sequential.world_runs` the paired ones.
- **Data live: a failing baseline stops the audit** with a message (exit code 2) unless every
  baseline run met the expectation or `--allow-failing-baseline` (`LiveConfig.allow_failing_baseline`)
  is given.
- **Nothing judged is not "not found".** An agents, data live or research live audit in which no
  mutated world produced a judged run (every run errored or could not be judged; baseline runs do
  not count) is `INCONCLUSIVE`.
- **Report schema 0.9.** New optional fields: `evidence_grade` and `observation` on findings,
  `multiplicity` on cases, status `OBSERVED_FAILURE`. Reports in schema 0.4 to 0.8 still load.
  Update any script that treats every finding of a live report as a rate statement.
- **Tests.** `tests/test_finding_grades.py`: 5% random failures over 8 worlds (small) or 50 worlds
  (`pytest -m statistical`), the two grades through the agents, data and research packs, the CLI
  gate and export selection, a failing data baseline, no judged run. Existing tests that encoded the
  old counts or statuses are changed and listed in the pull request.
- **Review follow-up.**
  - *Live data replay and export.* Every live data finding (and the verification of a minimized
    world) now has a replay artifact (`findings/<id>/replay.json`) that exists, and `data replay`
    runs it: it checks the reference answer on the recorded world, the recorded comparison of each
    agent answer with it, and what any code the agent returned gives on the world. It says the
    agent was not rerun. An agent that returned only an answer has no code recorded, and none is
    invented. `data export` writes the dataset, the question, the reference `gold.py`, the expected
    answer and the recorded observation; before, a live finding named replay files that were never
    written and exported empty. A finding with no artifact names no replay path.
    `data export` also no longer fails on an empty export into a new directory.
  - *Minimized-world verification is reported apart.* `extensions.data.verification` records its
    runs and failures; its finding has `search_scope: minimized_verification`. It can decide the
    case status, but is not among the generated worlds or in `multiplicity`, and the headline
    separates the two.
  - *The default gate stays `none`.* A rate-based gate is opt-in: `--fail-on rate-increase`
    (recommended for generated-world CI) or `observed-failure` (stricter). `data audit` gains
    `--fail-on`. Tests pin the default with the option omitted.
  - *Unassessed worlds.* A fixed MCP world with no validator keeps `validity.status:
    NOT_ASSESSED` in the world list, its findings and the case (the case used to read `VALID` with
    no tier); no tier is claimed, the report says so beside each finding, and the grade text says
    it is conditional on the world as run. An `INVALID` world is still not run.
  - *The report model checks the evidence.* `RATE_INCREASE` needs a sequential decision of
    `RATE_INCREASE` and an agreeing rate claim; `OBSERVED_FAILURE` needs a recorded judged failure
    and no decided rate. A tampered report is refused when it is loaded.
  - *Ranking.* Domain-validated, structurally validated and other `COUNTEREXAMPLE_FOUND`, then
    `OBSERVED_FAILURE`, then `INCONCLUSIVE` and `UNSUPPORTED`, then `NOT_FOUND_WITHIN_BUDGET`. Before,
    an observation, an inconclusive case and a counterexample with no assessed tier tied.
  - *Export without a trace.* `agents export` accepts a finding whose run called no tool (no
    `trace.jsonl`) and writes an empty trace; a malformed trace or a missing world still fails.
  - *Wording.* The expected claims under no effect is a nominal upper bound (worlds tested x 0.05),
    not a measured rate or a family-wise guarantee.
  - *Not closed:* a research finding's grade is decided on the searched world while the minimized
    world is shown (N5; a 0.9.0 release blocker in the findings ledger). The report now says so.


## 0.8.1 - Hotfix

A hotfix for 0.8.0. It changes no report schema (still 0.8). The release was built and tested
offline.

### Security

- **`data export` wrote files outside its output directory.** The data pack took file names from
  the `data_files` keys of a report and joined them to the output directory without checking them,
  so a report with a key such as `../../x.txt` or an absolute path wrote outside it. The same trust
  was placed in other names read from a report. Affected: `data export` (and the data report
  writer) in 0.6.0 to 0.8.0; the data pack first shipped in 0.6.0. An attack needs someone to run
  the command on a report written by somebody else. Every path read from a report is now joined
  with `isitright.core.paths.contained_path`, which refuses an absolute path, a drive or UNC
  prefix, any `..` component, an NTFS stream name and any path that resolves outside the base
  (links included). `data export`, `data replay`, `research export`, `agents export` and
  `agents replay` exit with code 2 and write nothing outside the output directory. `SECURITY.md`
  now covers the agent, data and research packs and report import and export. Do not run `data
  export` from 0.6.0 to 0.8.0 on a report you did not write.

### Fixed

- **Rate comparisons in the research and data packs were unsound before 0.8.1.** The research pack
  paired runs 5 to 16 of a world against a baseline run that never happened and was assumed to
  pass; the data pack reused its baseline outcomes in a cycle. With equal failure rates in both
  worlds the research rule claimed a rate increase in about 6% of audits at a 30% failure rate and
  27% at 50%. A rate claim (`RATE_INCREASE`) from 0.8.0 in these two packs should be treated as
  unsupported. A world is now paired only with baseline runs that were made, a run that errored or
  could not be judged is left out of its pair, and the report says how many pairs the comparison
  rests on. The research pack's case-level `stability`, which pooled worlds, is removed; the
  baseline counts are in `extensions.research.baseline.counts`.
- **Every agent run is under the budget.** The research pack checked the run budget only for world
  runs. Baseline runs after the first, minimization runs and confirmation runs now check it and
  record their cost, and an errored run keeps its cost. The agents pack's minimization steps check
  the budget before each trial. If the run budget is spent before a finding's confirmation run, the
  finding is reported on the unminimized world and says so.
- **Replay commands exist and survive moving the report.** The SQL report printed `isitright replay`
  (the command is `isitright sql replay`), the research report printed a bare file name, and the
  data and agents reports printed none. Each report now prints the right command with the report
  file's location as a placeholder in angle brackets (`<report.json>`), which the reader replaces
  with where the file is; artifact paths are stored relative to the report file. Nothing in a
  report, a replay artifact or a printed hint names the directory the audit wrote to, so a
  downloaded CI artifact replays from any directory.
- **An agents report and its scenario can both move.** The report stores the scenario reference
  as you typed it (it stored an absolute path made at run time). `isitright agents replay` takes
  `--scenario REF` to say where the scenario is now, and a recorded reference that cannot be
  loaded exits with code 2 and names `--scenario`; `rerun_eval_case` takes a reference too.
- **`runs/*/mcp.json` names no path of the machine that wrote it.** Once a run is over, the paths
  in the file that lie inside the output directory are rewritten relative to it and the scenario is
  the reference as typed (the agent still gets absolute paths while it runs). The interpreter in
  `command` is left as it is.
- **An agents report no longer fails to build** when a world id or an invariant name uses a verdict
  word (`wrong-zip`, `no-failure-allowed`): the headline points at the report, which keeps the name.
- **The unordered SQL row comparison no longer recurses once per row** (a `RecursionError` on
  thousands of equal rows) and is no longer quadratic for exact values: 100,000 identical rows
  compare in well under two seconds. Tolerance matching is an iterative maximum flow over classes
  of equal rows.

### Changed

- **At the default settings the research and data packs report counts, not rate claims.** A world
  has at most as many pairs as the baseline has runs (4 in research, 3 in data by default), and a
  rate increase needs 7 discordant pairs at the default test. To allow a claim, use 16 baseline
  runs (research `--runs 16`; data `--baseline-runs 16 --max-trials 16`): in a simulation, a rise
  in failures from 10% to 70% was detected 86% of the time with 16 baseline runs and 3.7% of the
  time with 7. A fresh baseline run for every pair, as the agents pack makes, is planned for
  0.9.0.
- In the data pack a world now runs at most as many times as there are baseline runs; it used to run
  up to `max_trials` with the baseline outcomes cycled.

### Documentation

- Corrected statements the code does not support: semantic fixtures are drafts and most are not
  yet reviewed; the agent command starts in the launch directory, not the run directory, with your
  full environment; principle 7 no longer implies the agent is contained; ties under `ORDER BY`
  are compared by position and not detected; the pairing rule per pack; exit code 1 also means a
  replay that did not reproduce, and a SQLite `INCONCLUSIVE` exits 0. The CI guide warns that
  `agent.log` can hold secrets.

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
