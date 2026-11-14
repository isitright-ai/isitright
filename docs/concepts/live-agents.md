# Live agents

A live agent is slow, costs money and can pass and fail on the same world. A SQL query is none of
those. Everything on this page exists because of that difference.

## Observed failure versus rate claim

isitright makes two kinds of statement and never turns the first into the second.

| | Observed failure | Rate claim |
|---|---|---|
| Says | In this recorded, replayable run, an objectively checked rule was violated | This world raises the agent's failure rate |
| Needs | One run | Repeated baseline and perturbed runs and a statistical test |
| Report field | Counts, for example 6 of 8 | `stability.rate_claim` and `stability.sequential`, only with adequate evidence |

A reproducible violation is useful evidence about one run. It does not show that the world made
failure likelier. The agent may fail the original world too.

## Baseline first

Before any perturbed world, the baseline world runs `--trials` times (`--baseline-trials` sets a
different count). Two things follow:

- A **flaky baseline** is reported first, because it weakens every later finding.
- The baseline's recorded calls become the **baseline trace**, which drives screening.

## Choosing which worlds to run

A [scenario](../agents/write-a-scenario.md) can generate thousands of valid worlds (about fourteen thousand for the shop). Most tell
you nothing: the agent never reads what changed, or the right action does not change. Running all of
them live is not affordable, so `agents run` ranks them.

**Screening, without the agent.** For each candidate world, isitright replays the baseline trace on
that world's simulated service and runs the [oracle](oracles-and-roles.md):

| Class | Meaning | Priority |
|---|---|---|
| `WRONG_IF_UNCHANGED` | The trace replays identically and the oracle says the old behavior is now wrong | Highest |
| `STALE` | A response the agent saw differs from the recorded one, so the recording says nothing here | Normal |
| `UNSCREENABLE` | No usable trace, the oracle cannot judge, or the world is unobservable | Normal |
| `RIGHT_IF_UNCHANGED` | The trace replays identically and the oracle is satisfied | Lowest |

Screening is a heuristic ranking. It never removes a world from the report. A world that was not
reached is listed as `NOT_RUN` with the reason, never as passing, and a `RIGHT_IF_UNCHANGED` world
can still fail if the agent is not deterministic.

**Ranking** (`--ranking`). `diverse` (default) takes the best-screened world of every stratum (family
chain, target chain, role) first, then the second best of every stratum, and so on. `screening` is
strict class order, `coverage` orders by feature coverage, `random` is a seeded shuffle.
`isitright agents order` re-ranks a finished run offline and free, to show how many worlds each
ordering would have needed before the first finding.

**Stopping rules.** A stratum stops after `--stratum-patience` worlds (default 10) without a finding.
The run stops after a stretch of consecutive worlds that added no uncovered feature and no finding.
The stretch is the larger of `--run-patience` (default 30) and `--run-patience-share` (default 0.10)
of the worlds ranked, so it grows with the universe: a fixed 30 is a long stretch among 300 worlds
and a short one among 6,000. The report states the number used. In a measurement on the shop
scenario with a scripted agent whose findings are rare, the fixed 30 stopped after 288 of 6,000
worlds and kept 5 of 21 distinct findings; 10% of the universe kept all 21 (and all 7 of a universe of
600), at 4,789 worlds run. It is one scenario and two scripted agents; the cost is more runs. `0` turns
a rule off (`--run-patience-share 0` restores the fixed number).

!!! warning "Default changed in 0.9: a run can now use more paid agent runs"
    The run stopping rule used to stop after 30 consecutive worlds that added nothing new. It now
    stops after the **larger of 30 and 10% of the worlds ranked** (`--run-patience-share 0.10`).
    **The consequence is more runs:** among 1,000 ranked worlds the quiet stretch is 100 worlds, not
    30, so the rule fires much later or never, and a search goes on until it reaches `--max-worlds`
    (default 50 for `agents run`, 40 for `data audit`), `--max-runs`, `--max-money` or `--max-seconds`. Every extra world is at least one more
    agent run, and each is a paid model call if your agent calls a hosted model. The default keeps
    more of the distinct findings when findings are rare (measured on one scenario: 21 of 21
    instead of 5 of 21 at 6,000 worlds) and costs more to get them.
    Whether 10% is right for your scenario is something to measure, not assume: see
    [Tuning the run rule](#tuning-the-run-rule).
    **Set a spend limit on every real run** (`--max-money`, `--max-runs`) and `--max-worlds` to the
    number of worlds you are willing to pay for. `--run-patience-share 0` restores the old fixed
    rule.
 A stopped stratum is reported as "no finding in n of m worlds"
with the reason. That is not evidence of correctness.

## Tuning the run rule

Whether 10% is right depends on your scenario, your agent and how rare its findings are. Measure it
on your own scenario instead of trusting the default:

1. **Make one run with both rules off** and a cap you are willing to pay for. It is the only run
   that costs anything: baseline runs plus (worlds run x `--trials`) agent runs.

   ```console
   isitright agents run --trust-code --scenario my_scenario.py:SCENARIO      --agent-command "..." --worlds generated --attempts 2000 --max-worlds 100 --trials 1      --no-sequential --stratum-patience 0 --run-patience 0 --max-money 20 --max-runs 150      --output-dir artifacts/tuning-run
   ```

2. **Replay the rules offline and free** over the worlds that run executed:

   ```console
   isitright agents stopping --report artifacts/tuning-run/report.json --trust-code
   ```

   It prints, for each `--run-patience-share` (`--shares 0,0.02,0.05,0.1,0.2,0.5`), the patience
   that share gives, the worlds the rule would have run, the worlds with a finding it would have
   reached, the strata with a finding it would have reached (a stratum is a family chain, a target
   and a role: the measure of distinct findings), and the position of the last finding it reached.

3. **Pick the smallest share that still reaches the strata you care about.** Each world a share
   adds is `--trials` more paid runs of your agent, so the "worlds run" column is the price.

What it cannot tell you: the replay covers only worlds the tuning run executed (a run that was
capped or stopped early understates what a small share would have run); a stochastic agent gives a
different table each run; and it is the agent you ran that is measured. For a free first look, run
the same two steps with a scripted agent (the shop's `careless` and `reference` agents are the
examples). That shows where the scenario's findings sit in the order, not where your agent's do.
`isitright data audit` has no replay command; its `--max-worlds` default is 40, so the rule rarely
matters there.

## Sequential testing per world

Each world runs in pairs with the baseline (its run *i* against baseline run *i*) until a sequential
probability ratio test on discordant pairs decides, up to `--max-trials` pairs (default 16).

- Alpha 0.05 and beta 0.2, against an alternative where 80 percent of discordant pairs go against the
  world. The false-claim rate is at most 0.05 at *any* look, so stopping early is safe.
- Decisions: `RATE_INCREASE` (a rate claim), `NO_INCREASE_AT_EFFECT` (evidence against an increase of
  that size only), `UNDECIDED`, and `NO_DISCORDANCE` (after `--trials` pairs, nothing went against the
  world: counts only, no claim).
- There is no correction across worlds. A rate claim is per world, and the case-level `stability`
  is counts only.
- When a world needs more pairs than the baseline has, extra baseline runs are made, and billed.

`--no-sequential` runs `--trials` per world with counts only, and a rate claim then needs an exact
McNemar test on at least 8 paired runs.

## Minimization through noise

For a finding with more than one [mutation](worlds-and-mutations.md#mutations), `--minimize` shrinks the mutation path by delta debugging.
Each candidate subset is judged by repeated runs, and a smaller path is kept only after a test said
it still fails. The path is replaced only when every single removal was tested and did not reproduce.
Inconsistent evidence returns the unminimized path. It costs runs, so it is off by default.

## Budgets

Budgets are in worlds, runs, seconds and money. `--max-money` stops the search once the cost the
agent reports reaches the budget; for that, the agent must report a cost for every run (see
[Run your agent](../agents/run-your-agent.md)). The report's `search.budget.runs` records what was
spent and what stopped the search.
