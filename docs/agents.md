# Tool-using agents over MCP (the MCP pack)

`isitright agents` checks whether an agent that passes a task still behaves well when the world it
works in changes in a small, valid way. You **declare** a service as a scenario: its entity
schema, constraints, tools, service parameters, hints from the task text, and an oracle. The core
generates the valid worlds, serves each one to your agent over MCP, records every call and the
final state, judges each run, and writes a report you can replay offline.

It is an evidence generator. A finding says the agent's behavior differed from a stated oracle in
a stated world. It does not say whether the agent, the scenario or the policy is at fault:
`attribution_status` is always `UNDETERMINED`.

## Concepts

| Term | Meaning |
|---|---|
| Scenario | A `McpScenario`: world spec, tools with simulated handlers, base state, hints, oracle. Trusted Python |
| World | A state plus response edits and timers, with the mutation path that produced it |
| Mutation target | `state` (what is true), `response` (what one tool call returns), `timing` (a state change after a matching call) |
| Hints | What the task text, tool schemas and baseline trace say matters (`lookup`, `ordering`, `gate`, `scope`, `threshold`, `trace`) |
| Oracle | Invariants over `(before, after, trace)` plus a reference procedure that recomputes the right behavior in any world |
| Role | Computed per world: `control` (the reference procedure acts), `trap` (it does nothing), `unjudgeable` |
| Validity tiers | `STRUCTURAL`, `DOMAIN_VALIDATED`, `REACHABLE`, `TASK_CONSISTENT`, `OBSERVABLE` |
| Fidelity | `SIMULATED` by default: your handlers stand in for the service |

**Why controls.** Zero violations in a trap world cannot tell a careful agent from one that
refuses everything. A control world, where acting is right, can. The report marks controls
`DISCRIMINATING` only if the agent reached the expected behavior in each control world at least
once, and `NOT_DISCRIMINATING` otherwise.

**Cannot judge.** Generated worlds will reach cases the oracle's author did not anticipate. The
scenario states its assumptions (`ScenarioOracle.judgeable` returns the reason when a world is
outside them) and such worlds are reported `CANNOT_JUDGE` and counted, never scored.

**Unobservable.** Tool declarations list which entity fields each read tool shows
(`ToolSpec.exposes`). A mutation that changes only fields no read tool exposes (a refund that
already exists, when no tool lists refunds) is flagged `unobservable`. That is a finding about the
tool contract, not about the agent.

## Quick start (no API key)

The booking scenario and a scripted agent need no key. With the `mcp` extra installed:

```console
set DEMO_AGENT_MODE=careless
isitright agents run --trust-code ^
  --scenario examples/agents/booking_scenario.py:SCENARIO ^
  --agent-command "python examples/agents/demo_agent.py" ^
  --worlds fixed --trials 1 --output-dir artifacts/agents-demo
```

On POSIX shells use `export DEMO_AGENT_MODE=careless` and `\` for line continuation. The modes are
`careless` (always cancels), `refuse` (never cancels) and `careful` (applies the policy). Replay
and export:

```console
isitright agents replay --trust-code --report artifacts/agents-demo/report.json
isitright agents export artifacts/agents-demo/report.json --output evals/booking.jsonl
```

## The shop support desk

`examples/agents/shop/` is a retail support-desk scenario with five tools over a plain JSON state,
and a task whose policy has six rules. It was written by three authors so that fixtures and checks
do not agree merely because one hand wrote both: the service and the scripted agents are one
author's, the invariants, the right behavior and a reference procedure (`oracle.py`) another's,
and the agent under test (`shop_agent.py`) a third's. `oracle.py` and `shop_agent.py` are kept as
received.

`scenario.py` declares the shop: the entity schema (customers with embedded payment methods,
orders, payments, refunds), constraints (payments sum to the order total, no order from the
future), service parameters, hints, prior operations (the service's own cancel and refund tools)
and the oracle. It does not list worlds: `--worlds generated` produces about ten thousand valid
worlds from two levels of generic mutations. The 24 hand-written worlds remain as `--worlds fixed`,
a regression fixture. Running the agent on all of them is not the default. `agents run` ranks the
eligible worlds by coverage of (family, target, role), three single mutations for every
composition, leaves out worlds the oracle cannot judge or the agent cannot observe, and runs them
in that order until a budget stops it: `--max-money`, `--max-runs`, `--max-seconds`, or
`--max-worlds` (default 50, a safety rail rather than a recommendation). The report says how many
worlds were generated, selected and left out, and why (`extensions.mcp.selection`, and a note in
`search.notes`). A world you name with `--world` is always run. Ranking is a stand-in for
screening without the agent (0.5).

## Declaring a scenario

```python
from isitright.packs.mcp.model import Layout, McpScenario, ScenarioOracle, ToolDef, Invariant
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.hints import Hint, Hints
from isitright.core.spec import ToolSpec, WorldSpec

schema = EntitySchema(collections=[CollectionSpec(name="orders", key="id", fields=[...])])
tools = [ToolDef("cancel", "Cancel an order.", {"type": "object"}, cancel, writes=True)]
SCENARIO = McpScenario(
    id="refunds",
    task="...",
    tools=tools,
    spec=WorldSpec(id="refunds", schema=schema, tools=[ToolSpec(name="cancel", writes=True)]),
    base=layout.from_service(initial_service_state, schema.keys()),
    layout=Layout(keyed=("orders",)),
    oracle=ScenarioOracle("ref", [Invariant("no_double_cancel", "...", check)], reference),
    hints=Hints(
        [Hint(kind="gate", args={"collection": "orders", "field": "status", "allows": ["pending"]})]
    ),
)
```

- **State.** Handlers receive the service's own JSON `dict` and must be deterministic given state
  and arguments (this makes a recorded run replayable). `Layout` maps it to and from the entity
  state. A hint that names a collection or field the entity model lacks is an error at load time.
- **Oracle.** `reference(call)` drives the tools like a careful agent (`call(tool, **arguments)`
  returns the parsed result or raises `ToolCallError`). If it writes, the world is a control. An
  agent run meets the oracle when its cancellations, refunds and other writes equal the
  reference's (`normalize`, `normalize_call`), so "exactly once" is part of the right behavior.
  Invariants get copies of the record; one that raises is a scenario bug and stops the run.
- **Fixed worlds.** `fixed_worlds=[FixedWorld(...)]` keeps hand-written worlds, with an optional
  `Expectation` and callable `Interference`s. Declarative timers (`Timer`) are used for generated
  worlds. A change is traced as a `__world_change__` pseudo-event, excluded from call counts and
  re-applied by replay.
- Scenarios are **trusted local code**. The CLI refuses to import one without `--trust-code`.

## Running your own agent

The agent is any command that accepts an MCP configuration. For every run isitright creates a
run directory (`runs/<world>/<trial>/`) containing:

| File | Written by | Purpose |
|---|---|---|
| `mcp.json` | runner | Standard `mcpServers` config; the server entry runs `python -m isitright.packs.mcp.serve` for this world |
| `task.txt`, `world.json` | runner | The task text, and the world (state, response edits, timers) |
| `trace.jsonl` | server | Every tool call, argument, result and error flag |
| `state_before.json`, `state_after.json` | server | The service state at the start and at the end (hidden from the agent) |
| `agent.log` | runner | The agent's stdout and stderr |

`{mcp_config}`, `{task_file}` and `{run_dir}` are substituted into the command's arguments and
exported as `ISITRIGHT_MCP_CONFIG`, `ISITRIGHT_TASK_FILE`, `ISITRIGHT_RUN_DIR`, `ISITRIGHT_WORLD`.
Exit code 0 is a completed run, non-zero is `SUBJECT_ERROR`, and exceeding `--timeout` kills the
agent and its server (`TIMEOUT`). An agent may write `transcript.json` (`provider`, `model`,
`sdk_versions`, `settings`, `stop_reason`, and `usage`: one entry per model call with
`input_tokens`, `output_tokens` and `cost`); the runner records the stack under test and the
cost. `--max-money` needs every usage entry to state its `cost`: if a completed run does not, the
run is refused with exit code 2 (after that first run) instead of running unbounded. Use
`--max-runs` or `--max-seconds` for agents that do not report cost.

## Stochastic subjects

The default is `--trials 4` runs of the baseline world and of each world. Reports give counts
(for example 6 of 8). A **rate claim** (this world raises the failure rate) needs at least 8 paired
runs per arm and an exact McNemar test on discordant pairs at alpha 0.05, and the report names the
test and the pair counts. Below that, `stability` carries counts and a note only. A flaky baseline
is reported first. `--max-money` stops the search once the cost the agent reports reaches the
budget; `search.budget.runs` records what was spent and what stopped it.

## Reading the report

`report.json` follows [`schemas/report-0.4.schema.json`](../schemas/report-0.4.schema.json) (see
[contracts](contracts.md)). The scenario is one case. Notable fields: `worlds` (every world with its
role, validity tiers, oracle outcome and counts), `findings` (per world: oracle results, stability,
world diff, mutation path with the hints behind it), `controls`, `stability` (baseline counts),
`search` (attempts, rejections by reason, families run and skipped, budget per hint group) and
`extensions.mcp` (the runs, the stack under test, the command).

## CLI

```
isitright agents run --scenario REF --agent-command CMD --trust-code
        [--worlds generated|fixed|all] [--trials N] [--world ID ...] [--max-worlds N, default 50]
        [--max-money X] [--max-runs N] [--max-seconds S] [--timeout SECONDS] [--output-dir DIR]
        [--fail-on none|invariant-violation|any-finding]
isitright agents replay --report report.json --trust-code [--findings-only]
isitright agents export report.json --output cases.jsonl
```

Exit codes: `0` completed, `1` internal error or `INCONCLUSIVE`, `2` invalid input (including no
valid world), `3` the opt-in `--fail-on` policy triggered.

## Limits

- No simulated user, noise-tolerant minimization or screening without the agent (planned for 0.5).
- Handlers are yours: `SIMULATED` means a finding is evidence about your stand-in for the service.
- The transport is stdio. The server process (and most agents) need the MCP SDK: `isitright[mcp]`.
- The agent command runs with your permissions and network. isitright does not sandbox it.
- Developed and tested on Windows; the timeout kill uses `taskkill /T` there and a process group
  elsewhere, so rely on the Linux CI run for the POSIX path.
