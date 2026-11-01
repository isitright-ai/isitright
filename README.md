# isitright

`isitright` audits agent evals. Point it at your agent and the eval cases that currently pass. It
searches for small, valid changes to the world under which a pass no longer holds, and returns each
one as a minimized, replayable counterexample. You can add each counterexample back to your eval set
as a new case.

**Documentation: [docs.isitright.ai](https://docs.isitright.ai)**: quick starts, concepts, guides for
both packs, and prompt templates that draft hints, constraints and scenarios for you to review.

## What it does

An eval case checks your agent in one world: one database, one set of orders, one clock. A pass
shows the agent did the right thing there, not why. isitright changes the world in valid but unusual
ways, works out what the right answer now is, and checks whether your agent still gets it.

**A text-to-SQL agent.** Your gold query `SUM(amount_owed - amount_collected)` and the agent's
`SUM(amount_owed) - SUM(amount_collected)` both return 130 on your test database, so the case passes
execution accuracy. isitright copies a row and sets `amount_collected` to `NULL`, a state your schema
allows. The queries now return 70 and 170. isitright shrinks the database to the smallest one that
shows this (two rows) and writes it out so you can read and replay it.

**A tool-using agent.** Your support agent may cancel a booking only if it was made in the last 24
hours, the airline cancelled a flight, or it is a business booking. Your eval is a booking from five
days ago: the right behavior is to decline, and the agent does. An agent that declines everything
passes too. isitright reruns the case in a world where the booking is 23 hours 59 minutes old, where
the right answer is to cancel, and reports the runs in which your agent did not.

Two packs ship on one shared core:

| You have | Use | World | Where it runs |
|---|---|---|---|
| A tool-using agent that talks MCP | `isitright agents run` | An entity state behind MCP tools | An MCP server per run (`SIMULATED`) |
| Text-to-SQL output (reference and candidate queries) | `isitright sql check` / `suite` | A database | SQLite or PostgreSQL (`NATIVE_ISOLATED`), DuckDB (`EMULATED`) |

**What a finding means.** isitright runs your subject (the agent or the generated query) and an
*oracle*, a reference that recomputes what is right for the changed world, and reports the worlds
where they disagree. A disagreement does not say who is wrong: the reference is an implementation
too, so attribution stays `UNDETERMINED` until you decide. Finding nothing
(`NOT_FOUND_WITHIN_BUDGET`) means nothing was found in the worlds tried, never that the agent is
correct. Each finding also reports how valid the changed world is, whether outputs came from the real
engine, and for live agents the run counts against an unchanged baseline. See
[Evidence](https://docs.isitright.ai/concepts/evidence/).

## Install

Python 3.11 or newer.

```console
python -m pip install isitright                 # SQLite and the core
python -m pip install "isitright[mcp]"          # + MCP agent pack
python -m pip install "isitright[postgres]"     # + native PostgreSQL (disposable local server)
python -m pip install "isitright[duckdb]"       # + DuckDB emulation
python -m pip install "isitright[all]"
```

The quick starts below use files from `examples/`, which the package does not ship:

```console
git clone https://github.com/isitright-ai/isitright.git
cd isitright
python -m pip install -e ".[all]"
```

From a source checkout you can also use `uv sync --locked --extra dev --extra all`.

## Quick start: SQL

```console
python examples/sqlite/create_database.py example.sqlite
isitright sql check --database example.sqlite \
  --reference examples/sqlite/reference.sql --candidate examples/sqlite/candidate.sql \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start
```

The two queries agree on the sample rows, but isitright finds a small state (an amount missing)
where they differ, and writes `case_report.md`, `case_report.json`, a hand-readable
`counterexample.sql` and a `replay.json`. Then replay it, export it as a new eval case, or audit a
whole suite:

```console
isitright sql replay artifacts/quick-start/case_report.json
isitright sql export artifacts/quick-start/case_report.json --output evals/generated.jsonl
isitright sql suite --database example.sqlite --cases examples/sqlite/cases.jsonl \
  --constraints examples/sqlite/constraints.yaml --output-dir artifacts/quick-start-suite
```

The suite report ranks cases by evidence strength: domain-validated counterexamples first.
`--engine postgres --schema schema.sql` audits against PostgreSQL on a disposable local server, and
`--fail-on domain-counterexample` sets a CI exit code. The same from Python:

```python
from isitright import check

report = check(
    engine="sqlite",
    database="example.sqlite",
    reference_sql="SELECT SUM(amount_owed - amount_collected) FROM tribute",
    candidate_sql="SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute",
)
print(report.divergence_status, report.headline)
```

Next: [SQL quick start](https://docs.isitright.ai/get-started/sql/) (with the output explained),
[audit your own suite](https://docs.isitright.ai/sql/audit-a-suite/), and
[supported SQL](https://docs.isitright.ai/sql/supported-sql/).

## Quick start: an agent over MCP

Needs `isitright[mcp]`. The repository includes a support-desk shop (`examples/agents/shop/`): a
customer asks to cancel and refund "my most recent order". The scenario declares the shop's
entities, tools, constraints and hints, plus an oracle. No API key is needed: scripted agents stand
in for a careful, a careless and a refuse-everything agent.

```console
isitright agents run --trust-code \
  --scenario examples/agents/shop/scenario.py:SCENARIO \
  --agent-command "python examples/agents/shop/scripted_agent.py" \
  --worlds fixed --trials 1 --output-dir artifacts/shop
```

This runs the 24 hand-written regression worlds with the careful agent (about three minutes). Select
the scripted behavior with `SHOP_AGENT_MODE=careless|refuse|reference`. The report (`report.json`
and `report.md`) lists each world with its role, validity tiers, run counts against the baseline,
and the findings. Replay a run offline, and export findings as new eval cases:

```console
isitright agents replay --report artifacts/shop/report.json --trust-code
isitright agents export artifacts/shop/report.json --output evals/shop-generated.jsonl
```

`--worlds generated` (the default) generates valid worlds from the declaration, about twelve
thousand for the shop, and runs the most promising ones first until a budget stops it
(`--max-money`, `--max-runs`, `--max-seconds`). A world that was not reached is reported as **not
run**, never as passing. Generation alone takes minutes for the shop; start with
`examples/agents/booking_scenario.py` for a quick generated-worlds run.

Worlds have **roles**: a *control* is a world where acting is right, a *trap* one where doing
nothing is right. Without controls, "no violations" cannot be told from "refuses everything".
For a live agent, runs repeat against a baseline, and only a sequential test's `RATE_INCREASE`
decision is a claim that a world raises the failure rate; below that you get counts.

Next: [agent quick start](https://docs.isitright.ai/get-started/agents/) (with the output explained),
[write a scenario](https://docs.isitright.ai/agents/write-a-scenario/),
[run your own agent](https://docs.isitright.ai/agents/run-your-agent/), and
[onboarding with an LLM](https://docs.isitright.ai/onboarding/), which drafts hints, constraints and
scenarios for you to review.

## Concepts

The [concepts overview](https://docs.isitright.ai/concepts/) defines these with one running example:

| Concept | Meaning |
|---|---|
| World, state, atoms | A state is data: collections of entities plus parameters. Atoms (entities) are the unit of diffs and minimization |
| Entity model | Collections with typed fields, keys, references and dependent clusters (an order with its payments) |
| Constraints and validity | Rules that check states and guide generation, and tiers (`STRUCTURAL`, `DOMAIN_VALIDATED`, ...) saying how many a state passed |
| Mutations | A small described change: to `state`, to a tool `response`, or `timing` (a state change after a call). Composed to depth two |
| Hints | What the task, schemas, programs and baseline trace say matters. They prioritize the search; unhinted mutations still run |
| Subjects and oracles | What is tested (a query or a live agent) and the reference that recomputes what is right |
| Evidence | One [report schema](https://docs.isitright.ai/reference/report/): divergence, validity, fidelity, oracle, run counts, attribution |

## Extend it (experimental)

You can add mutators, constraints, hints, oracles and hosts, and write packs for new domains. A
custom mutator gets search, validity checks, minimization, replay and reporting for free. The
extension API is public and **experimental** until a pack is written by someone other than its
author. See [Write a mutator or host](https://docs.isitright.ai/guides/extending/).

## Safety

The tool never modifies your data or systems: perturbed worlds live in disposable instances,
in-process engines or isitright-hosted fakes. SQL is a single read-only statement under an
authorizer, `query_only` and time and row limits. Each MCP run is a fresh server process with a
process-tree kill on timeout. Credentials are runtime-only and never written to reports. A live agent
runs with your permissions and network; isitright does not sandbox it. Scenarios, mutators, oracles
and validators are Python and load only with `--trust-code`.

## Development

```console
uv sync --locked --extra dev --extra all
uv run ruff check . && uv run mypy src && uv run python tools/export_schemas.py --check
uv run pytest
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), which also covers building the documentation. Semantic
fixtures (entity schemas, constraints, hints, oracle rules, expected results) are owner-approved;
drafts carry a "Proposed fixture" header.

## Background

The approach combines property-based testing with differential and metamorphic testing, applied to
your own evals. Related work and how isitright differs: [About](https://docs.isitright.ai/about/).

## License

MIT. See [LICENSE](LICENSE).
