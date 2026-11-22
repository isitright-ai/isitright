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
| Statistics | `--sequential` (default) with `--max-trials N` (default 20); `--no-sequential` for counts only |
| Shrink findings | `--minimize` (costs runs) |
| Add [hints](../concepts/hints.md) | `--hints hints.yaml` |
| Per-run timeout | `--timeout SECONDS` (default 300) |
| CI | `--fail-on none\|invariant-violation\|any-finding\|rate-increase\|observed-failure` (see [CI](../guides/ci.md#live-agent-gates)) |
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
| `COUNTEREXAMPLE_FOUND` | A paired sequential test decided that a world fails more often than the baseline (grade `RATE_INCREASE`) | Open the finding; run `agents replay`; review before blaming the agent |
| `OBSERVED_FAILURE` | A judged run failed on a mutated world that ran and was not found invalid, and no paired test decided a higher failure rate (grade `OBSERVED_FAILURE`). How far the world was validated is stated for each world: a fixed world with no validator is `NOT_ASSESSED` | Open the finding and replay it. It is evidence to inspect, not a claim about the failure rate. With `--no-sequential` every finding is of this kind |
| `INCONCLUSIVE` | Nothing usable. "The agent command produced no completed run", or "no mutated world produced a judged run" (every run of every mutated world errored or could not be judged; baseline runs do not count) | Read `agent.log` in a run directory |

The report's `worlds` list shows every world run and the best-ranked worlds not run. A stopped
stratum reads "no finding in n of m worlds". Neither is evidence of correctness.

## What is in a finding

A fixed world with no validator runs and is graded, and its `validity` stays `NOT_ASSESSED` (no tier is claimed, in the world's entry, the finding, the case and `report.md`); a world whose validator reports problems is `INVALID` and is not run. Read a grade on a `NOT_ASSESSED` world as conditional on that world as run.

For each finding: its evidence grade, the world and its role, which invariants or expectations failed, the [oracle](../concepts/oracles-and-roles.md)'s
outcome, [validity tiers](../concepts/validity-and-fidelity.md#validity-tiers), the world diff, the mutation path with the hints that led to it, run
counts against the baseline and the sequential test's record. `example_run_dir` points at a run
directory with the full trace. `observation` holds failures out of judged runs on the world, with errored and
unjudged runs beside them and a 95% Wilson interval (descriptive: it ignores the number of worlds), and the same
for the baseline runs made for the world's pairs. The report also says how many worlds were tested, that the
per-world decisions are not corrected for that number (there is no family-wise guarantee), and a nominal upper bound on the number of false rate-increase claims expected
if no mutation had any effect (at most worlds tested times 0.05; the test's real rate is lower). The console summary,
`report.md` (headline and an "Observed failures" section, shown whatever the paired test said) and `report.json`
carry the same. See [Evidence](../concepts/evidence.md) and the
[report schema](../reference/report.md).

## Costs, in practice

- Screening costs nothing: it replays the baseline trace on each candidate world without the agent.
- A world is first run `--trials` times (default 4). Only a world with a failed run among them goes on
  to the sequential test, whose pairs are new runs: a run of the world and a fresh baseline run, so a
  world that goes the full `--max-trials` pairs costs 4 + 40 runs at the defaults. A world with no
  failure costs `--trials` runs and no baseline run. The baseline runs made before the search
  (`--trials`) are not reused as pairs, and the screening runs take no part in the test: choosing a
  world because it failed does not bias the test.
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
isitright agents export artifacts/first-run/report.json --output evals/agent-findings.jsonl [--include-observed]
```

Export writes the findings graded `RATE_INCREASE`. A finding graded `OBSERVED_FAILURE` is left out, and the
command says how many; `--include-observed` exports them too.

See [Replay and export](../guides/replay-and-export.md).

## Exit codes

`0` completed, `1` internal error or `INCONCLUSIVE`, `2` invalid input (including no valid world, or
`--max-money` with an agent that reports no cost), `3` the opt-in `--fail-on` policy triggered.
