# Third-party servers

A [scenario](write-a-scenario.md)'s tools are usually simulated: you write handlers and isitright owns the state. If the
service is an MCP server you did not write, and it keeps its state in a file or a SQLite database,
isitright can run the **real server** instead. Findings then have `NATIVE_ISOLATED` [fidelity](../concepts/validity-and-fidelity.md#execution-fidelity) rather
than `SIMULATED`.

## How it works

Give the scenario an `ExternalServer` (`isitright.packs.mcp.external`): how to start the server,
and a **state adapter** that seeds the server's storage from a world (`seed`) and reads it back
(`read`).

| Adapter | Storage |
|---|---|
| `JsonLinesFile` | A JSON-lines file |
| `SqliteFile` | A SQLite database |

For each run, the proxy host starts the real server on a copy of the storage in the run directory,
forwards the agent's calls, traces each one, and writes `state_after.json` from the storage after
every call, hidden from the agent. The reference procedure runs against the same kind of server, so
roles (control or trap) come from the real thing.

`examples/agents/memory/` declares the Memory reference MCP server this way, a knowledge graph in a
JSON-lines file. Its docstring has the setup: install `@modelcontextprotocol/server-memory` with
npm (Node 24 or newer) and point `ISITRIGHT_MEMORY_SERVER` at the package's `dist/index.js`. No
account or key is needed. `tests/fixtures/servers/` has a small SQLite-backed server to read.

## What to do differently

- **[Entity schema](../concepts/worlds-and-mutations.md#the-entity-model) and [hints](../concepts/hints.md)** come from the task text and the server's tool schemas, as for any
  scenario.
- **Use a small `--attempts`.** The reference procedure runs a real server for each candidate, which
  is slow. Run with a few hundred attempts first.
- **Seed carefully.** The adapter writes the world into the server's own storage format. If the
  server validates its storage on load, a world the adapter cannot express is rejected.

## Limits

- World generation uses **state mutations only**. Response edits and timers need middleware the
  server does not have.
- Screening is `UNSCREENABLE`: there is no in-process service to replay the [baseline](../concepts/live-agents.md#baseline-first) trace on, so the
  ranking has less to go on.
- Replay re-judges the recorded state and trace instead of re-executing the calls.
- Only servers whose state lives in a JSON-lines file or a SQLite database are supported. A server
  backed by a network service or another store needs a new adapter.
