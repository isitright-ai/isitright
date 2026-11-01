# Run an audit

This page maps goals to flags. The reasoning behind the defaults is in
[Live agents](../concepts/live-agents.md).

## A first real run

Start small and read the report before scaling up.

```console
isitright agents run --trust-code --scenario my_scenario.py:SCENARIO \
  --agent-command "python my_agent.py --config {mcp_config} --task {task_file}" \
  --worlds generated --attempts 2000 --max-worlds 10 --trials 4 \
  --max-money 5 --output-dir artifacts/first-run
```

This runs the baseline 4 times, then up to 10 ranked worlds, and stops when 5 dollars of reported
cost is spent.

## Flags by goal

| Goal | Flags |
|---|---|
| Choose which worlds | `--worlds generated` (default), `fixed` (hand-written regression worlds) or `all`; `--world ID` runs exactly that world (repeatable) |
| Control generation | `--attempts N` candidate worlds visited (default 20000, which takes minutes for a large [scenario](write-a-scenario.md)); `--max-worlds N` is a safety rail after ranking (default 50) |
| Repeat runs | `--trials N` runs per world and for the baseline (default 4); `--baseline-trials N` when the baseline should differ |
| Spend limits | `--max-money X` (needs agent-reported cost), `--max-runs N`, `--max-seconds S` |
| Stop on rules | `--stratum-patience N` (default 10) and `--run-patience N` (default 30); `0` turns a rule off |
| Order worlds | `--ranking diverse` (default), `screening`, `coverage`, `random` |
| Statistics | `--sequential` (default) with `--max-trials N` (default 16); `--no-sequential` for counts only |
| Shrink findings | `--minimize` (costs runs) |
| Add [hints](../concepts/hints.md) | `--hints hints.yaml` |
| Per-run timeout | `--timeout SECONDS` (default 300) |
| CI | `--fail-on none\|invariant-violation\|any-finding` |
| Output | `--output-dir DIR` (default `artifacts/agents-run`) |

A world you name with `--world` always runs. A generated world's id is `g<hash>_<families>`; the hash
covers what the mutations change, so the same world has the same id under any seed, hint arm or
attempt budget, and the id from a report can be used in a later run.

## Reading progress

The terminal prints one marker per run: `.` as expected, `V` invariant violated, `N` expected
behavior not met, `?` not judged, `E` run did not complete. Then one line per world, and a summary
with the run count and elapsed time.

## Interpreting the outcome

| Console says | Means | Do next |
|---|---|---|
| [`NOT_FOUND_WITHIN_BUDGET`](../concepts/evidence.md#divergence_status), `Controls: DISCRIMINATING` | No finding in the worlds run, and the agent acted where acting was right | Check how many worlds ran versus `NOT_RUN`. Raise the budget if the run stopped early |
| `NOT_FOUND_WITHIN_BUDGET`, `Controls: NOT_DISCRIMINATING` | No violations, but the agent never acted in a control world | The agent may refuse everything. This is not a clean result |
| `COUNTEREXAMPLE_FOUND` | A world where an invariant was violated or the expected behavior was not met | Open the finding; run `agents replay`; review before blaming the agent |
| `INCONCLUSIVE` | Nothing usable. Often "the agent command produced no completed run" | Read `agent.log` in a run directory |

The report's `worlds` list shows every world run and the best-ranked worlds not run. A stopped
stratum reads "no finding in n of m worlds". Neither is evidence of correctness.

## What is in a finding

For each finding: the world and its role, which invariants or expectations failed, the [oracle](../concepts/oracles-and-roles.md)'s
outcome, [validity tiers](../concepts/validity-and-fidelity.md#validity-tiers), the world diff, the mutation path with the hints that led to it, run
counts against the baseline and the sequential test's record. `example_run_dir` points at a run
directory with the full trace. See [Evidence](../concepts/evidence.md) and the
[report schema](../reference/report.md).

## Costs, in practice

- Screening costs nothing: it replays the baseline trace on each candidate world without the agent.
- Extra baseline runs are made, and billed, when a world needs more pairs than the baseline has.
- `isitright agents order --report report.json --trust-code` re-ranks a finished run's executed
  worlds under each ordering and prints how many worlds each needs before the first finding. It runs
  nothing and costs nothing. Only executed worlds are placed, so a run stopped early is biased toward
  its own ranking.

## Add hints

```console
isitright agents hints propose --trust-code --scenario my_scenario.py:SCENARIO \
  --proposer examples/proposers/model_proposer.py:PROPOSER --output hints.yaml
# edit hints.yaml: set each hint's status to confirmed, proposed or rejected
isitright agents hints confirm hints.yaml --accept lookup_by_name
isitright agents run ... --hints hints.yaml
```

`propose` needs a proposer, which isitright does not ship: `examples/proposers/model_proposer.py` shows
where a model client plugs in (its key is read from the environment when called, never stored). If
you would rather paste a prompt into a chat, see [Agent setup](../onboarding/agents.md#hints) and
write the file by hand; `confirm` and `--hints` read it the same way. `confirm --scenario REF
--trust-code` re-checks each hint against the scenario first.

## Replay and export

```console
isitright agents replay --report artifacts/first-run/report.json --trust-code [--findings-only]
isitright agents export artifacts/first-run/report.json --output evals/agent-findings.jsonl
```

See [Replay and export](../guides/replay-and-export.md).

## Exit codes

`0` completed, `1` internal error or `INCONCLUSIVE`, `2` invalid input (including no valid world, or
`--max-money` with an agent that reports no cost), `3` the opt-in `--fail-on` policy triggered.
