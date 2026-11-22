# Minimization and replay

A raw counterexample can be a database with thousands of rows or an agent run with dozens of calls.
Nobody can review that. isitright shrinks every finding and makes it reproducible before it reports it.

## Minimization

Minimization is **delta debugging**: remove pieces of the changed world and keep a removal only if the
disagreement survives and the world stays valid. It works on atoms (rows, records), and every step
re-checks validity, so the result is still a world that could exist.

| [Subject](subjects.md) | What shrinks | Result |
|---|---|---|
| A query (`ARTIFACT`) | The whole world: first drop everything the queries do not reference, then shrink the background rows | Typically two or three rows, small enough to read |
| A live agent (`AGENT`) | The *[mutation](worlds-and-mutations.md#mutations) path*: the list of changes that produced the world, usually one to three | The fewest changes that still make the agent fail |

An agent only sees what it queries, so shrinking the background of an agent's world would change what
it reads and add noise. Agent minimization is also noisy: each candidate path is judged by repeated
runs and a smaller path is kept only when a statistical test says it still fails. It costs runs, so it
is off by default (`--minimize`).

The [SQL quick start](../get-started/sql.md) shows it: a four-row counterexample reduced to two rows.

## One world per finding

A finding is about one world, and everything in it is built from that world: the diff, the validity
tiers, the run counts, the reproduction result, the replay artifact and the export. Minimization may
not change what the evidence is about.

- A SQL query pair keeps a smaller world only if its difference is of the kind that was found: the
  candidate errors, the row counts differ, or the counts agree and the values differ. A removal that
  turns one disagreement into another is not kept. If the minimized world does not reproduce when it
  is rerun, the finding shows the world the search found.
- For a warehouse, the shown world is the one the native engine confirmed. If only the larger world
  differs natively, that world is shown and the minimized one is attached as emulated and unverified.
- A live agent's minimal mutation path is run as a world of its own (`--trials` runs and, after a
  failure, fresh baseline pairs, as for any searched world). It replaces the searched world in the
  finding only if it fails and, when the searched world's paired test decided a rate increase, its own
  paired test decided one too. Otherwise the finding stays on the searched world and the minimization
  record says why the minimal path is not shown.
- The mutations named in a finding are the ones whose changes the shown world still has.

Each finding records the fingerprint of the world it shows and, for each part, the fingerprint of the
world that part was built from; the report model refuses a finding where they differ. See
[the report schema](../reference/report.md#one-world-per-finding).

## Replay

Replay answers "can I see this fail again, without trusting the search?"

- **SQL:** rebuilds the minimized world on the recorded engine from the concrete rows in the report
  and checks that both queries produce the recorded outputs.
- **Agents:** re-executes the recorded tool calls against the simulated service, in the world recorded
  with the run, and checks the final state and verdicts match. It does not call your agent.

Replay works from the concrete minimized world, **not from a random seed**. A seed reproduces a search
only as long as the search code is unchanged; a concrete world reproduces the finding forever.

## Export as an eval case

Every counterexample can be exported as a new [eval case](../guides/replay-and-export.md#export) in the pack's format (a fixture database with
both queries; a world with its task, trace and verdict). One audit then leaves behind a regression
test per finding. See [Replay and export](../guides/replay-and-export.md).

## Reproducibility

A report records the seed, configuration, hashes of the inputs, the mutation path and the replay
artifact. Timing fields vary between runs; every other field is deterministic for a fixed database,
configuration, seed, package version and engine version.
