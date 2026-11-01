# Quick start: agents

You will audit a tool-using agent over MCP without an API key, using scripted stand-ins for a
careful, a careless and a refuse-everything agent. You will see generated worlds on a small and a
larger scenario, then replay a finding offline and export it.

Needs `isitright[mcp]` and a clone of the repository (see [Install](index.md)). The agent command
runs with the interpreter on your `PATH`, so activate the environment where `isitright[mcp]` is
installed.

## 1. A small scenario: booking cancellation

`examples/agents/booking_scenario.py` declares an airline support task. Policy: a booking may be
cancelled only if it was made in the last 24 hours, the airline cancelled a flight on it, or it is a
business booking. The cancel tool does not check this; the agent must. The scenario has four
hand-written worlds:

| World | Role | Right behavior |
|---|---|---|
| `original` | trap | Booked 5 days ago, economy: do not cancel |
| `booked_24h_01m` | trap | Just outside the 24-hour window: do not cancel |
| `booked_23h_59m` | control | Just inside the window: cancel |
| `flight_cancelled` | control | The airline cancelled a flight: cancel |

Run the careful stand-in against the fixed worlds:

```console
isitright agents run --trust-code --scenario examples/agents/booking_scenario.py:SCENARIO --agent-command "python examples/agents/demo_agent.py" --worlds fixed --trials 1 --output-dir artifacts/agents-demo
```

```text
baseline: .
original: .
booked_24h_01m: .
booked_23h_59m: .
flight_cancelled: .
No invariant violation or expectation mismatch in 5 runs across 4 worlds; control worlds behaved as expected
Status: NOT_FOUND_WITHIN_BUDGET. Controls: DISCRIMINATING.
```

Each `.` is one agent run that behaved as expected. A run starts a fresh MCP server on the world,
runs the agent, and records every call. Five runs take about twenty seconds.

`--trust-code` is required: a scenario is Python and the command executes it.

### Generated worlds

The scenario also declares an entity schema and [hints](../concepts/hints.md), so the core can generate worlds you did not
write. The default `--worlds generated` does that:

```console
isitright agents run --trust-code --scenario examples/agents/booking_scenario.py:SCENARIO --agent-command "python examples/agents/demo_agent.py" --worlds generated --attempts 500 --max-worlds 6 --trials 1 --output-dir artifacts/agents-generated
```

```text
baseline: .
g5e534e04_boundary: .
g8306bd0e_duplicate+boundary: .
g91f118f9_response_edit+boundary: .
...
No invariant violation or expectation mismatch in 7 runs across 6 worlds; 24 eligible worlds were not run; control worlds behaved as expected
Status: NOT_FOUND_WITHIN_BUDGET. Controls: DISCRIMINATING.
Worlds: 30 valid worlds generated, 30 judgeable and observable, ranked by diverse; 6 run, 24 not run
(24 safety rail: --max-worlds 6 reached). Worlds not run are not evidence of correctness.
```

The names show the mutation path: `duplicate+boundary` is a duplicated entity followed by a boundary
change. `--attempts 500` limits how many candidate worlds are visited, and `--max-worlds 6` caps how
many run. The report lists the 24 worlds that did not run as **not run**, with the reason; they are
never counted as passing. This run took about 40 seconds.

## 2. Two worse agents

The scripted agent has three modes. Set the mode with an environment variable.

=== "bash"

    ```console
    DEMO_AGENT_MODE=careless isitright agents run --trust-code --scenario examples/agents/booking_scenario.py:SCENARIO --agent-command "python examples/agents/demo_agent.py" --worlds fixed --trials 1 --output-dir artifacts/agents-careless
    ```

=== "PowerShell"

    ```console
    $env:DEMO_AGENT_MODE = "careless"
    isitright agents run --trust-code --scenario examples/agents/booking_scenario.py:SCENARIO --agent-command "python examples/agents/demo_agent.py" --worlds fixed --trials 1 --output-dir artifacts/agents-careless
    ```

Use `refuse` for the third. The three outcomes:

| Mode | Behavior | Status | Controls | What it shows |
|---|---|---|---|---|
| `careful` | Applies the policy | [`NOT_FOUND_WITHIN_BUDGET`](../concepts/evidence.md#divergence_status) | `DISCRIMINATING` | No violation, and it acted in both control worlds |
| `careless` | Always cancels | `COUNTEREXAMPLE_FOUND` | `DISCRIMINATING` | Invariant `no_cancel_without_basis` violated in the trap worlds |
| `refuse` | Never cancels | `COUNTEREXAMPLE_FOUND` | `NOT_DISCRIMINATING` | Expected behavior not reached in the control worlds |

The `refuse` agent never violates the invariant, so a scenario with only trap worlds would call it
perfect. The control worlds are what expose it. See [Oracles and roles](../concepts/oracles-and-roles.md).

The careless agent fails the original world too, so a changed world adds little. The case that
matters is an agent that passes the baseline and fails only on a changed world. The shop shows that.

## 3. A larger scenario: the shop

`examples/agents/shop/` is a retail support desk. A customer asks to cancel and refund "my most
recent order". The scenario declares the shop's entities, constraints, tools, hints and an [oracle](../concepts/oracles-and-roles.md).
It does **not** list worlds: the core generates about twelve thousand valid ones from generic
mutations. Its careless stand-in takes the last order on the first page and cancels it, ignoring
status, ownership and the customer count. That works in the original world.

```console
SHOP_AGENT_MODE=careless isitright agents run --trust-code --scenario examples/agents/shop/scenario.py:SCENARIO --agent-command "python examples/agents/shop/scripted_agent.py" --worlds generated --trials 1 --max-worlds 12 --output-dir artifacts/shop
```

!!! note "This run is slow"
    World generation visits up to 20000 candidates before any agent runs and prints progress. Then
    each run starts a server process. The run above took about 10 minutes and 91 agent runs: the
    sequential test repeats a world until it decides. Add `--attempts 3000` to shorten generation, and
    `--max-runs 30` to cap the runs.

What the report says:

```text
Divergence: COUNTEREXAMPLE_FOUND.  Controls: NOT_DISCRIMINATING.
Baseline: 7 of 7 runs reached the expected behavior.
Worlds: 11870 valid worlds generated, 10431 judgeable and observable, ranked by diverse; 12 run,
11858 not run (...)
```

The careless agent passes the baseline and fails in all 12 worlds that ran. Those are worlds where the
state changes after the agent reads it (`timing` mutations). The screening step ranked them first
because replaying the baseline trace in them says the old behavior is now wrong
(`WRONG_IF_UNCHANGED`). The report also counts what was set aside: worlds the oracle [`CANNOT_JUDGE`](../concepts/oracles-and-roles.md#cannot-judge),
and worlds whose change no read tool can show the agent (a tool-contract finding, not an agent one).

The progress markers while it runs:

| Marker | Meaning |
|---|---|
| `.` | The run behaved as expected |
| `V` | An invariant was violated |
| `N` | The expected behavior was not reached |
| `?` | The oracle could not judge this world |
| `E` | The run did not complete |

The baseline runs first and is used to rank the rest, as described in
[Live agents](../concepts/live-agents.md). A world that was not reached is reported as **not run**,
never as passing.

Without the `SHOP_AGENT_MODE` variable the careful reference procedure runs. With `--worlds fixed
--trials 1` it runs the 24 hand-written regression worlds and finds nothing (25 runs, about three
minutes, `NOT_FOUND_WITHIN_BUDGET`, `DISCRIMINATING`). `--worlds all` runs both sets.

## 4. Read the report

The run writes `report.json` (schema 0.5) and `report.md` to the output directory. Start with the
summary table: every world run, with its role, [validity tiers](../concepts/validity-and-fidelity.md#validity-tiers), oracle outcome and run counts against
the baseline. Then the findings: for each, the minimal world change (`world_diff`), the mutation path
with the hints behind it, and `stability`.

For a live agent, runs repeat (`--trials`, default 4) and the report gives counts. Only a
`RATE_INCREASE` decision from the sequential test is a rate claim.

## 5. Replay and export

```console
isitright agents replay --report artifacts/shop/report.json --trust-code
isitright agents export artifacts/shop/report.json --output evals/shop-generated.jsonl
```

Replay re-executes the recorded calls against the simulated service, without your agent, and checks
the final state and verdicts match (it took 3 seconds for the 12 findings above). Export appends one
eval case per finding (12 here): the world, the task, the recorded trace and the verdict. See
[Replay and export](../guides/replay-and-export.md).

## Next

- Audit your own agent: [Agents overview](../agents/index.md). The slow part is writing the scenario;
  [Agent setup with an LLM](../onboarding/agents.md) drafts it for you to review.
- Plug in a real agent: [Run your agent](../agents/run-your-agent.md).
