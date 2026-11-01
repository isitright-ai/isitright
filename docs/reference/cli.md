# CLI reference

```text
isitright --version
isitright sql    check | suite | replay | export | slice
isitright agents run | replay | export | order | hints propose | hints confirm
```

Run any command with `--help` for the options as your installed version defines them.

## `isitright sql check`

Compare one query pair on perturbed worlds of a database or schema.

| Option | Default | Notes |
|---|---|---|
| `--reference FILE` | required | Gold query, one read-only `SELECT` |
| `--candidate FILE` | required | Generated query |
| `--engine sqlite\|postgres\|duckdb` | `sqlite` | `postgres` is native; `duckdb` is emulated |
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
| `--run-patience N` | `30` | `0` = never |
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

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed |
| `1` | Internal error or `INCONCLUSIVE` |
| `2` | Invalid input, including no valid world |
| `3` | The opt-in `--fail-on` policy triggered |
