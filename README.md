# isitright

`isitright` audits agent evals. Point it at your agent, your environment and the eval cases
that currently pass. It searches for valid changes to the world under which a pass no longer
holds, and returns each one as a minimized, replayable counterexample with an honest account of
how strong the evidence is. Each counterexample can be added back to your eval set as a new case.

It works on two kinds of agents, through two packs on one core:

| You have | Use | World | Host |
|---|---|---|---|
| A tool-using agent and a simulated service | `isitright agents run` | An entity state behind MCP tools | An MCP server per run (`SIMULATED`) |
| Text-to-SQL output (reference and candidate queries) | `isitright sql check` / `suite` | A database | SQLite or PostgreSQL (`NATIVE_ISOLATED`), DuckDB (`EMULATED`) |

A disagreement is evidence, not a verdict about who is wrong: the reference is an implementation
too, and attribution is always `UNDETERMINED` until a human decides. Finding nothing within a
budget (`NOT_FOUND_WITHIN_BUDGET`) is never evidence of correctness.

## What the tool does

You describe the world: its entities and constraints, the tools or the schema, and what the task
says matters (**hints**). The core perturbs the world with generic families (a second customer
with the same name, an order exactly at the page size, a NULL in an aggregated column, a status
one step off the gate, a duplicated row, an unseen timestamp offset) and composes two mutations
when one is not enough. It keeps only valid worlds, runs your agent or your queries in each, and
compares the outcome with an oracle that recomputes the right answer for the changed world.

Every result keeps these apart: divergence, validity (with tiers), execution fidelity, the oracle
and whether it could judge, run counts against a baseline, and attribution.

## Install

Python 3.11 or newer.

```console
python -m pip install isitright                 # SQLite and the core
python -m pip install "isitright[mcp]"          # + MCP agent pack
python -m pip install "isitright[postgres]"     # + native PostgreSQL (disposable local server)
python -m pip install "isitright[duckdb]"       # + DuckDB emulation
python -m pip install "isitright[all]"
```

From a source checkout: `uv sync --locked --extra dev --extra all`.

## Quick start: an agent over MCP

The repository includes a support-desk shop (`examples/agents/shop/`): a customer asks to cancel
and refund "my most recent order". The scenario declares the shop's entities, tools, constraints
and hints, plus an oracle written by someone else (invariants and a reference procedure). No API
key is needed: the scripted agents stand in for a careful, a careless and a refuse-everything
agent.

```console
isitright agents run --trust-code \
  --scenario examples/agents/shop/scenario.py:SCENARIO \
  --agent-command "python examples/agents/shop/scripted_agent.py" \
  --worlds fixed --trials 1 --output-dir artifacts/shop
```

`--worlds generated` (the default) generates the valid worlds from the declaration (about fourteen
thousand for the shop) and chooses which ones to run: the baseline runs first, its recorded trace
is replayed on every candidate world without the agent (*screening*), and the worlds are run in
that order until a rule or a budget stops the run (`--stratum-patience`, `--run-patience`,
`--max-money`, `--max-runs`, `--max-seconds`; `--max-worlds`, default 50, is a safety rail). A world
that was not reached is reported as **not run**, never as passing. `fixed` runs the 24
hand-written regression worlds; `all` runs both. Select the scripted behavior
with `SHOP_AGENT_MODE=careless|refuse|reference`. The report (`report.json`, schema 0.5, and
`report.md`) lists each world with its role, validity tiers, run counts against the baseline, and
the findings. Replay any run offline, and export findings as new eval cases:

```console
isitright agents replay --report artifacts/shop/report.json --trust-code
isitright agents export artifacts/shop/report.json --output evals/shop-generated.jsonl
```

Worlds have **roles**, computed by the scenario's reference procedure: a *control* is a world
where acting is right, a *trap* one where doing nothing is right. Without controls, "no
violations" cannot be told from "refuses everything"; a scenario whose controls are never reached
is reported `NOT_DISCRIMINATING`. A world the oracle cannot judge is `CANNOT_JUDGE`, counted and
reported, never scored silently. A change no read tool can show the agent is flagged
unobservable: a finding about the tool contract, not about the agent.

For a live agent, runs are repeated (`--trials`, default 4) against a baseline. The report gives
counts. Each world is run in pairs with the baseline until a sequential probability ratio test on
discordant pairs decides (false claims at most 5 percent over the whole sequence of looks); only
its `RATE_INCREASE` decision is a rate claim, and the report names the test, its looks and its
decision. Below that you get counts only. `--minimize` shrinks a finding's mutation path through
the noise with repeated runs, and `--max-money` stops the search when the reported cost reaches the
budget. A third-party MCP server (a file or SQLite database it owns) can be the service: see
`examples/agents/memory/`. See [docs/agents.md](docs/agents.md).

## Quick start: SQL

```console
python examples/sqlite/create_database.py example.sqlite
isitright sql check --database example.sqlite \
  --reference examples/sqlite/reference.sql --candidate examples/sqlite/candidate.sql \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start
```

The two queries agree on the sample rows, but `isitright` finds a small state (an amount missing)
where they differ, and writes `case_report.md`, `case_report.json` (schema 0.5), a hand-readable
`counterexample.sql` and a `replay.json`.

## For text-to-SQL readers

The SQL pack tests two read-only queries (a gold query and a generated one) against changes to
the database. It is the same idea as test-suite accuracy and bounded SQL equivalence checkers: a
query pair can agree on today's rows by accident. Example: `SUM(owed - collected)` against
`SUM(owed) - SUM(collected)` agree on complete rows and differ as soon as one amount is `NULL`;
the minimal counterexample is two rows.

```console
isitright sql check --engine postgres --schema examples/postgres/schema.sql \
  --reference examples/postgres/reference.sql --candidate examples/postgres/candidate.sql \
  --output-dir artifacts/postgres-example
isitright sql suite --database example.sqlite --cases examples/sqlite/cases.jsonl \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start-suite
isitright sql replay artifacts/postgres-example/case_report.json
isitright sql export artifacts/postgres-example/case_report.json --output evals/generated.jsonl
```

- **Engines.** SQLite from a database file (with or without rows) or from DDL; PostgreSQL from
  DDL on a disposable local server (native); DuckDB runs translated PostgreSQL SQL and is labeled
  `EMULATED`, never default CI evidence (PostgreSQL integer division is a known false
  positive).
- **Comparison.** Multisets unless the reference query has a top-level `ORDER BY`
  (`--ordering auto|ordered|unordered`), positional columns by default, float tolerance. The policy
  is recorded in every report.
- **Validity.** Generated states are valid by construction (keys, references, unique columns) and
  checked against the engine and any JSON Schema constraints; reports say whether a counterexample
  is `STRUCTURAL` only or also `DOMAIN_VALIDATED`.
- **Minimization.** The state is reduced to a few rows (the lead example: two).
- **Suites.** Cases are isolated and ranked: domain-validated counterexamples first. `--fail-on
  domain-counterexample|any-counterexample` sets a CI exit code.
- **Limits.** One read-only statement, a documented subset of SQL; unsupported input is rejected,
  not weakened. See [docs/supported-sql.md](docs/supported-sql.md).

```python
from isitright import check

report = check(
    engine="sqlite",
    database="example.sqlite",
    reference_sql="SELECT SUM(owed - collected) FROM debts",
    candidate_sql="SELECT SUM(owed) - SUM(collected) FROM debts",
)
print(report.divergence_status, report.headline)
```

## Concepts

| Concept | Meaning |
|---|---|
| World, state, atoms | A state is data: collections of entities plus parameters. Atoms (entities) are the unit of diffs and minimization. |
| Entity model | Collections with typed fields, keys, references and dependent clusters (an order with its payments). |
| Constraints | Declarative data (`Range`, `OneOf`, `Unique`, `Aggregate`, row expressions) that both check states and guide generation. Python predicates are check-only and listed. |
| Hints | What the task, schemas, programs and baseline trace say matters: `lookup`, `ordering`, `gate`, `scope`, `threshold`, plus kinds you register. Hints prioritize; unhinted mutations still run on the remaining budget. |
| Mutations | `state`, `response` (what one tool call returns) or `timing` (a state change after a matching call). Depth two by default. |
| Evidence | One report schema ([docs/contracts.md](docs/contracts.md)) with run counts, validity tiers, fidelity, oracle, attribution. |

## Write your own mutator or host (experimental)

The extension API is public and **experimental** until a pack is written by someone other than
its author. A mutator proposes data, so it gets search, validity checks, minimization, replay and
reporting for free:

```python
from isitright.core.mutations import Mutation, SetField


class RoundTotals:
    family = "round_totals"
    target = "state"
    consumes = frozenset({"column"})  # the hint kinds this family reads

    def propose(self, spec, world, hints):
        for entity in world.state.entities("orders"):
            yield Mutation(
                family=self.family,
                description=f"orders[{entity['id']!r}].total rounded",
                edits=[
                    SetField(
                        collection="orders",
                        key=entity["id"],
                        path=["total"],
                        value=round(entity["total"]),
                    )
                ],
                touches=["orders.total"],
            )
```

Pass it with the built-ins to `isitright.core.search.search`, or compose built-in families by
name. A host implements `prepare(spec, world)` (a context manager that makes the world available
to a subject) and declares its `Fidelity`; the SQL pack's `SqliteHost.run_pair` and the MCP
pack's `ServiceRuntime` are the two working examples. A subject is anything that implements
`run(handle, task)`; an oracle implements `judge`. Everything above runs offline, on trusted code
only: scenarios, mutators, oracles and validators are Python and load only with `--trust-code`.

## Safety

The tool never modifies your data or systems: perturbed worlds live in disposable instances,
in-process engines or isitright-hosted fakes. SQL is a single read-only statement under an
authorizer, `query_only` and time and row limits. Each MCP run is a fresh server process with a
process-tree kill on timeout. Credentials are runtime-only and never written to reports.

## Development

```console
uv sync --locked --extra dev --extra all
uv run ruff check . && uv run mypy src && uv run python tools/export_schemas.py --check
uv run pytest
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Semantic fixtures (entity schemas, constraints, hints,
oracle rules, expected results) are owner-approved; drafts carry a "Proposed fixture" header.

## Background

The approach combines property-based testing with differential and metamorphic testing. Close
prior art for SQL is SpotIt, VeriEQL and test-suite accuracy; for benchmark auditing, EvalPlus
and the agentic benchmark checklist. isitright's additions are live, stochastic subjects with
budgets, worlds with validity tiers, oracles that recompute (and may be wrong), hosts with stated
fidelity, and evidence you can replay and export.

## License

MIT. See [LICENSE](LICENSE).
