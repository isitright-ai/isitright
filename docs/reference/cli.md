# CLI reference

```text
isitright --version
isitright sql    check | suite | replay | export | slice
isitright agents run | replay | export | order | hints propose | hints confirm
isitright data   check | audit | replay | export
```

Run any command with `--help` for the options as your installed version defines them.

## `isitright sql check`

Compare one query pair on perturbed worlds of a database or schema.

| Option | Default | Notes |
|---|---|---|
| `--reference FILE` | required | Gold query, one read-only `SELECT` |
| `--candidate FILE` | required | Generated query |
| `--engine sqlite\|postgres\|duckdb` | by `--dialect` | Where states run. `postgres` is native; `duckdb` is emulated. Without `--dialect`: `sqlite` |
| `--dialect sqlite\|postgres\|bigquery\|presto\|trino` | follows `--engine` | The SQL the queries are written in. `bigquery`, `presto` and `trino` run on `duckdb` |
| `--param NAME=VALUE` | none | Fills `<NAME>` and `{{ NAME }}` placeholders in both queries (repeatable) |
| `--column-policy positional\|by_name\|names_and_positions\|contained` | `positional` | `contained`: each reference column equals some candidate column, at any position |
| `--reference-columns 0,2` | all | Compare only these reference columns (0-based) |
| `--column-vectors` | off | Compare columns as independent sorted vectors when unordered |
| `--null-as-zero` | off | Count NULL as 0 when comparing |
| `--wall-time SECONDS` | none | Stop the search after this long; the report says it was stopped by the time cap |
| `--nested-scope path\|column` | `path` | Nested columns (BigQuery, Presto, Trino): generate and mutate only the paths the queries read, or every field of a column they read (the 0.7 behavior). New in 0.9 |
| `--confirm bigquery\|trino\|connection` | none | Re-run findings on a native host with the state inlined |
| `--connection MODULE:FUNCTION`, `--trust-code` | none | The function for `--confirm connection`: `run(sql) -> (columns, rows)` |
| `--bq-project`, `--max-bytes-billed`, `--env-file` | none, 100 MB | BigQuery project, cap on bytes billed per query, a file from which only `GOOGLE_APPLICATION_CREDENTIALS` is read |
| `--trino-host`, `--trino-port`, `--trino-user`, `--trino-catalog`, `--trino-schema` | `localhost`, 8080, `isitright`, `memory`, `default` | Trino server for `--confirm trino` |
| `--database FILE` | | SQLite file |
| `--schema FILE` | | DDL file (SQLite DDL for sqlite; PostgreSQL DDL for postgres and duckdb) |
| `--constraints FILE` | | JSON Schema domain rules, YAML or JSON |
| `--seed N` | `0` | |
| `--max-attempts N` | `500` | Candidate worlds |
| `--minimization-attempts N` | `500` | [Minimization](../concepts/minimization-and-replay.md) budget |
| `--timeout SECONDS` | `30.0` | Per query |
| `--max-result-rows N` | `10000` | |
| `--column-policy positional\|by_name\|names_and_positions` | `positional` | |
| `--ordering auto\|ordered\|unordered` | `auto` | `auto` requires order only when the reference has a top-level `ORDER BY` |
| `--float-mode exact\|isclose` | `isclose` | |
| `--float-rtol X`, `--float-atol X` | `1e-9`, `1e-12` | |
| `--output-dir DIR` | `artifacts/check` | |
| `--format json\|markdown\|both` | `both` | |
| `--fail-on none\|domain-counterexample\|any-counterexample` | `none` | Exit code 3 |
| `--verify-native` / `--no-verify-native` | on | Re-execute DuckDB findings on PostgreSQL when installed |
| `--gold-trusted` / `--gold-untrusted` | unknown | State that the reference query is right or is not known to be; the report says so beside a finding (0.7) |

Writes `case_report.json`, `case_report.md`, and for a counterexample `counterexample.sql` and
`replay.json`. For `postgres` and `duckdb` the output directory must not already exist.

## `isitright sql suite`

Audit a JSONL suite with per-case isolation and ranking. Takes the options above plus:

| Option | Default | Notes |
|---|---|---|
| `--cases FILE` | required | JSONL: `case_id`, `reference_sql`, `candidate_sql`, optional `question`; other fields are kept as metadata |
| `-v`, `--verbose` | | Every case and written artifact |
| `-q`, `--quiet` | | Totals and the report directory only |
| `--output-dir DIR` | `artifacts/suite` | Writes `suite_report.json`, `suite_report.md` and `cases/NNNN-<id>/` |

## `isitright sql replay REPORT`

Rebuild the first counterexample of a case report from its recorded world and compare both outputs.
Options: `--timeout` (30.0), `--max-result-rows` (10000).

## `isitright sql export REPORT --output FILE`

Append the report's counterexamples as eval cases, one JSON object per line.

## `isitright sql slice`

Cut a small SQLite database holding the rows the reference query used.

| Option | Default | Notes |
|---|---|---|
| `--database FILE` | required | |
| `--reference FILE` | required | |
| `--output PATH` | required | A new SQLite file |
| `--cap N` | `25` | Joined tuples of the reference query to keep |
| `--pad N` | `5` | Rows kept of each table only a subquery names |

## `isitright agents run`

Run an agent on the [baseline](../concepts/live-agents.md#baseline-first) and on every valid world of a [scenario](../agents/write-a-scenario.md).

| Option | Default | Notes |
|---|---|---|
| `--scenario REF` | required | `module:attr` or `file.py:attr`. The referenced code is executed |
| `--agent-command CMD` | required | `{mcp_config}`, `{task_file}`, `{run_dir}` are substituted |
| `--trust-code` | | Required: confirms the scenario is trusted code |
| `--worlds generated\|fixed\|all` | `generated` | |
| `--trials N` | `4` | Runs per world; also the baseline count |
| `--baseline-trials N` | | Baseline runs when they should differ |
| `--timeout SECONDS` | `300.0` | Per agent run |
| `--max-worlds N` | `50` | Safety rail after ranking |
| `--world ID` | | Run only this world, repeatable |
| `--attempts N` | `20000` | Candidate worlds the generation may visit |
| `--ranking diverse\|screening\|coverage\|random` | `diverse` | |
| `--stratum-patience N` | `10` | `0` = never |
| `--run-patience N` | `30` | `0` = never; the floor of the run rule |
| `--run-patience-share S` | `0.10` | The run rule stops after the larger of `--run-patience` and this share of the worlds ranked; `0` = the fixed number |
| `--max-trials N` | `16` | Most paired runs per world for the [sequential test](../concepts/live-agents.md#sequential-testing-per-world) |
| `--sequential` / `--no-sequential` | on | |
| `--minimize` / `--no-minimize` | off | Costs runs |
| `--hints FILE` | | A [hints](../concepts/hints.md) file; confirmed hints count as declared, others as proposed |
| `--max-money X` | | Needs agent-reported cost |
| `--max-runs N`, `--max-seconds S` | | |
| `--output-dir DIR` | `artifacts/agents-run` | |
| `--fail-on none\|invariant-violation\|any-finding` | `none` | Exit code 3 |

## `isitright agents replay`

`--report FILE --trust-code [--findings-only]`. Replay recorded runs offline and check they reproduce.

## `isitright agents export REPORT --output FILE`

Append the report's findings as eval cases (world, task, recorded trace, verdict).

## `isitright agents order`

`--report FILE [--trust-code] [--random-seeds N]` (default 100). Re-rank the executed worlds with each
ordering offline; prints how many worlds each needs before the first finding. Costs nothing.

## `isitright agents hints propose`

`--scenario REF --proposer REF --trust-code [--output hints.yaml]`. Ask a proposer for hints from
the task, policy and tool schemas, and write them to a file. The proposer is code and may call a
model.

## `isitright agents hints confirm FILE`

`[--accept NAME ...] [--scenario REF --trust-code]`. Mark proposed hints confirmed; they are then
used as declared. `--scenario` re-checks each hint against the scenario first. With no `--accept`,
every proposed hint is confirmed.

## `isitright data check TASKS`

`--programs FILE.jsonl --output DIR --trust-code [--attempts N] [--seed N] [--depth N] [--findings N]
[--timeout S] [--memory-mb N] [--reuse N] [--serial] [--cache DIR] [--resume] [--only TASK_ID ...]`.
Frozen audit of recorded programs on a task directory or a directory of them. `--reuse N` keeps a host
process for N runs (faster, less isolated). `--cache DIR` keeps finished runs on disk and `--resume`
continues an interrupted audit in an existing `--output` with the same settings; neither changes the
result. See [Data analysis agents](../data.md#long-audits-resume-and-the-run-cache).

## `isitright data audit TASK`

`--agent module:callable --output DIR --trust-code [--programs FILE] [--pass-env NAME ...]
[--baseline-runs N] [--max-trials N] [--max-worlds N] [--ranking diverse|screening|coverage|random]
[--stratum-patience N] [--run-patience N] [--run-patience-share S] [--max-runs N] [--max-money X]
[--max-seconds S] [--attempts N] [--seed N] [--agent-kwargs JSON] [--agent-timeout S] [--env-file FILE]`. `--attempts`
(default 300) sets both the frozen check that finds the minimized world and the live world search;
`--agent-kwargs` are the factory's keyword arguments as JSON; `--env-file` reads only the variables
named by `--pass-env` from a dotenv-style file (a variable already in the environment wins). Live
audit: the agent is run on ranked worlds, paired with its own baseline runs, in a separate process
that sees only the variables named by `--pass-env`.

## `isitright data replay REPORT`

`--trust-code [--finding N]`. Rerun a finding from its concrete minimized world.

## `isitright data export REPORT --output DIR`

Write each finding as an eval case: the dataset (CSV), the question, the gold program, the expected
answer, and an index `cases.jsonl`.

## `isitright research check CORPUS`

Audit a research agent on mutated corpora (see [Research agents](../research/index.md)).

```bash
isitright research check CORPUS --task task.json --output DIR \
  (--stand-in NAME | --agent module:attr | --agent-command "..." | --recorded-run run.json) \
  [--trust-code] [--hints hints.json] [--attempts 500] [--depth 2] \
  [--retriever bm25|hashed-dense|hybrid] [--support-judge quote-contains-answer|module:attr] [--seed N] [--runs K] [--max-runs N] \
  [--seconds S] [--max-money USD] [--timeout S] [--screen] [--no-minimize] \
  [--allow-failing-baseline] [--record-runs DIR] \
  [--fail-on none|domain-counterexample|any-counterexample]
```

`CORPUS` is a JSONL file or a directory. Choose exactly one subject. `--agent` and
`--agent-command` need `--trust-code`. An agent command receives `{mcp_config}`, `{task_file}` and
`{run_dir}` and writes `report.json` into `{run_dir}`. `--max-money` is refused for an agent that
reports no cost. The output directory holds `report.json`, `findings-cases.md`, and per finding
`N.replay.json` and `N.eval-case.json`.

`--support-judge` (new in 0.9) judges whether each cited quote supports its claim (L2) on the baseline run: `quote-contains-answer` is a shipped rule; `module:attr` or `file.py:attr` is a judge of your own and needs `--trust-code`. The result is under `extensions.research.support` of the case and changes no level or outcome. `--retriever` (new in 0.9) chooses the retriever behind the tools: `bm25` (the default, as in 0.8), `hashed-dense` (a deterministic hashed bag-of-words embedding, a stand-in for a dense retriever) or `hybrid` (reciprocal rank fusion of the two). The report and the replay artifact record the choice. The HTTP server for hosted agents is a module, `python -m isitright.packs.research.http_server`; see [Research agents](../research/index.md#http-for-hosted-agents).

## `isitright research replay ARTIFACT`

Reproduce a finding offline: the recorded tool calls must give the same results on the rebuilt
corpus, the recorded report must earn the recorded verdict, and a stand-in agent run again with the
recorded seed must give the same report. A live agent is not run again.

## `isitright research export REPORT --output DIR`

Write each finding as an eval case: the minimized corpus, the question and the expectation.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed |
| `1` | Internal error or `INCONCLUSIVE` |
| `2` | Invalid input, including no valid world |
| `3` | The opt-in `--fail-on` policy triggered |
