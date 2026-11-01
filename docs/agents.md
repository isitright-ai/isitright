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
orders with a JSON `items` field and its declared shape, payments, refunds), constraints (payments
sum to the order total, no order from the future), service parameters, hints, prior operations
(the service's own cancel and refund tools) and the oracle. It does not list worlds:
`--worlds generated` produces about fourteen thousand valid worlds from two levels of generic
mutations. The 24 hand-written worlds remain as `--worlds fixed`, a regression fixture.

## Choosing which worlds to run

A live run costs money and time, and most generated worlds tell us nothing: the agent never reads
what changed, or the right action is the same as before. `agents run` therefore does the
following, and reports each step.

1. **Baseline first.** The baseline world runs `--trials` times (`--baseline-trials` sets a different count). Its recorded calls are the
   *baseline trace*.
2. **Screening, without the agent.** Each candidate world's service replays the baseline trace and
   the oracle judges the result. Four classes:

   | Class | Meaning | Priority |
   |---|---|---|
   | `WRONG_IF_UNCHANGED` | The trace replays identically and the oracle says the old behavior is now wrong | Highest |
   | `STALE` | A response the agent saw differs from the recorded one, so the recording says nothing about this world | Normal |
   | `UNSCREENABLE` | No usable baseline trace, the oracle cannot judge, or the world is unobservable | Normal |
   | `RIGHT_IF_UNCHANGED` | The trace replays identically and the oracle is satisfied | Lowest |

   Screening is a ranking, not a verdict. It decides the order of live runs and never removes a
   world from the report: a world that was not reached is listed as **not run** (`run_status:
   NOT_RUN`, with the reason), never as passing. A `RIGHT_IF_UNCHANGED` world can still fail if the
   agent's behavior is not deterministic.
3. **Ranking (`--ranking`).** `diverse` (the default) takes the best-screened world of every
   stratum (family chain, target chain, role) first, then the second best of every stratum, and so
   on; `screening` is strict class order; `coverage` is the 0.4 order (feature coverage);
   `random` is a seeded shuffle. See `REPORT.md` of the 0.5 notes for the measured difference.
4. **Stopping rules.** A stratum stops after `--stratum-patience` worlds (default 10) with no
   finding; the whole run stops after `--run-patience` consecutive worlds (default 30) that added
   no uncovered feature and no finding. `0` turns a rule off. `--max-money`, `--max-runs` and
   `--max-seconds` are the real budgets; `--max-worlds` (default 50) is a safety rail after
   ranking, not a recommendation. A stopped stratum or run is reported as "no finding in n of m
   worlds" with the reason (`search.stopping`). That is not evidence of correctness.
5. **Sequential testing, per world.** Each world runs in pairs with the baseline (its run *i*
   against baseline run *i*) until a sequential probability ratio test on discordant pairs decides,
   up to `--max-trials` pairs (default 16). Boundaries are 1/alpha and beta on the likelihood ratio
   with alpha 0.05 and beta 0.2 against an alternative where 80 percent of discordant pairs go
   against the world, so the false-claim rate is at most 0.05 at any look. Decisions:
   `RATE_INCREASE` (a rate claim), `NO_INCREASE_AT_EFFECT` (evidence against an increase of that
   size only), `UNDECIDED`, and `NO_DISCORDANCE` (after `--trials` pairs nothing was against the
   world: counts only, no claim). Extra baseline runs are made, and billed, when a world needs
   more pairs than the baseline has. The record (test, looks, boundaries, decision) is in the
   finding's `stability.sequential`. There is no correction across worlds: a rate claim is per
   world, and the case-level `stability` is counts only. `--no-sequential` runs `--trials` per
   world with counts only.
6. **Minimization (`--minimize`, off by default).** For a finding with more than one mutation,
   delta debugging over the path's mutations judges each subset by repeated runs (a Bernoulli
   sequential test against the baseline's failure rate), and keeps a smaller path only after such
   a test said it still fails. The finding's `minimization` records the tests and their error
   bounds; the path is replaced only when every single removal was tested and did not reproduce.
   Inconsistent evidence returns the unminimized path.

A world you name with `--world` is always run.

**JSON values.** A field of type `json` is opaque unless a scope is declared: a `shape` on the
field, or a `json_path` hint such as `orders.items[*].price`. The `json_edit` family acts only
there (a leaf moved, a list element removed or duplicated, a key removed or set to null, each as
one whole-field edit). Without a rule that reads the content (`JsonSum`), such a world is
`STRUCTURAL` only, and its validity record says so.

## Proposed hints

Hints focus the generic families (`lookup`, `ordering`, `gate`, `scope`, `threshold`, `json_path`,
`trace`). You declare them in the scenario; a model can propose more from the task text, the
policy text and the tool schemas. isitright has the plumbing, not a model client:

```console
isitright agents hints propose --trust-code --scenario REF --proposer module:PROPOSER --output hints.yaml
# edit hints.yaml; then
isitright agents hints confirm hints.yaml --accept name1 --accept name2
isitright agents run ... --hints hints.yaml
```

A `HintProposer` is any object with `propose(request) -> list[Hint]` (`isitright.core.proposals`);
`examples/proposers/model_proposer.py` shows where a real client plugs in (its key is read from the
environment when called, never stored; the tests use a recorded response). Every proposed hint is
labeled `proposed`, and one the entity model cannot resolve is rejected with the reason. In the
file each hint has a `status`: `confirmed` is loaded as `declared`, `proposed` stays `proposed`
and `rejected` is dropped. **A proposed hint prioritizes the search and grants no validity tier**:
tiers come from constraints, reachability, the declared lookups and observability, and a proposed
lookup is not a declared one. The report's `search.hint_use` lists every hint with its provenance
and the worlds it led to.

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

## A third-party server as the service

The shop's handlers are simulated, so isitright owns its state. A server isitright did not write
owns its own, in a file or a SQLite database. Give the scenario an `ExternalServer`
(`isitright.packs.mcp.external`): how to start the server, and a state adapter that seeds its
storage from a world (`seed`) and reads it back (`read`): `JsonLinesFile` for a JSON-lines file,
`SqliteFile` for a database. For each run the proxy host (`serve_external`) starts the real server
on a copy of the storage in the run directory, forwards the agent's calls, traces each one and
writes `state_after.json` from the storage after every call (hidden from the agent). The reference
procedure runs against the same kind of server, so roles come from the real thing, and fidelity is
`NATIVE_ISOLATED`. Limits: world generation uses state mutations only (response edits and timers
need middleware the server does not have), screening is `UNSCREENABLE` (there is no in-process
service to replay the trace on), and replay re-judges the recorded state and trace instead of
re-executing the calls. `examples/agents/memory/` declares the Memory reference server this way
(setup in its docstring); `tests/fixtures/servers/` has a small SQLite-backed one.

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
`--max-runs` or `--max-seconds` for agents that do not report cost. A simulated user that is itself
a model can add `user_usage` (the same entries): the runner records `user_model_calls`,
`user_input_tokens`, `user_output_tokens` and `user_money` apart from the agent's, and `money` (what
`--max-money` counts) is then the agent's cost plus the user's.

Agents run with one thread for OpenBLAS, OpenMP and MKL (`OPENBLAS_NUM_THREADS`,
`OMP_NUM_THREADS`, `MKL_NUM_THREADS`) unless the environment sets them: several agent processes at
once, each with a server that imports numpy, could not start on a small machine otherwise.

A generated world's id is `g<hash>_<families>`. The hash covers what the mutations change, so the
same world has the same id under any seed, hint arm or attempt budget, and `--world` can name it
across runs (the attempt budget must still be large enough to reach it).

A `threshold` hint on a field may say where its cut-off value itself falls: `holds` (`above` or
`below`) is the side of the cut-off where the condition the hint names is true, and `inclusive`
says whether the cut-off value is on that side; they come together. A generated world that sits
exactly on the cut-off is judged only when the hint says so, and only if the reference procedure
agrees with it (the world must have the role of the neighbor on the side the hint puts it). With no
declaration the world is `CANNOT_JUDGE` ("the hint does not say whether that value is inside"),
because the reference's `<` or `<=` would otherwise decide the right answer.

`ScenarioOracle.ignored_writes` names tools whose successful calls are left out of the comparison
between the agent's writes and the reference's, for a write the policy allows besides what the
reference does. Invariants still see them.

`isitright agents order --trust-code --report REPORT` re-ranks the worlds a finished run executed
with each ranking (screening, diverse, coverage, and random averaged over `--random-seeds`) and
prints how many worlds each needs before the first finding. It runs nothing and costs nothing. Only
executed worlds are placed, so a run stopped early by patience or `--max-worlds` is biased toward
its own ranking.

## Stochastic subjects

The default is `--trials 4` runs of the baseline world and of each world. Reports give counts
(for example 6 of 8). A **rate claim** (this world raises the failure rate) comes from the
sequential test described above, or, with `--no-sequential`, from an exact McNemar test on at
least 8 paired runs at alpha 0.05; the report names the test and the pair counts. Below that,
`stability` carries counts and a note only. A flaky baseline is reported first. `--max-money` stops the search once the cost the agent reports reaches the
budget; `search.budget.runs` records what was spent and what stopped it.

## Reading the report

`report.json` follows [`schemas/report-0.5.schema.json`](../schemas/report-0.5.schema.json) (see
[contracts](contracts.md)). The scenario is one case. Notable fields: `worlds` (every world run, and the best-ranked worlds not run, with
role, validity tiers, oracle outcome, counts, screening class and rank), `findings` (per world: oracle results, stability,
world diff, mutation path with the hints behind it), `controls`, `stability` (baseline counts),
`search` (attempts, rejections by reason, families run and skipped, budget per hint group) and
`extensions.mcp` (the runs, the stack under test, the command).

## CLI

```
isitright agents run --scenario REF --agent-command CMD --trust-code
        [--worlds generated|fixed|all] [--trials N] [--baseline-trials N] [--world ID ...] [--max-worlds N, default 50]
        [--attempts N] [--ranking diverse|screening|coverage|random] [--stratum-patience N] [--run-patience N]
        [--max-trials N] [--sequential/--no-sequential] [--minimize]
        [--max-money X] [--max-runs N] [--max-seconds S] [--timeout SECONDS] [--output-dir DIR]
        [--fail-on none|invariant-violation|any-finding]
isitright agents replay --report report.json --trust-code [--findings-only]
isitright agents export report.json --output cases.jsonl
```

Exit codes: `0` completed, `1` internal error or `INCONCLUSIVE`, `2` invalid input (including no
valid world), `3` the opt-in `--fail-on` policy triggered.

## Limits

- No simulated user. Screening replays the baseline trace, so it is a heuristic: a changed world can change what the agent reads.
- Handlers are yours: `SIMULATED` means a finding is evidence about your stand-in for the service.
- The transport is stdio. The server process (and most agents) need the MCP SDK: `isitright[mcp]`.
- The agent command runs with your permissions and network. isitright does not sandbox it.
- Developed and tested on Windows; the timeout kill uses `taskkill /T` there and a process group
  elsewhere, so rely on the Linux CI run for the POSIX path.
