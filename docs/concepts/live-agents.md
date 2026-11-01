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
The run stops after `--run-patience` consecutive worlds (default 30) that added no uncovered feature
and no finding. `0` turns a rule off. A stopped stratum is reported as "no finding in n of m worlds"
with the reason. That is not evidence of correctness.

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
