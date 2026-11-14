# Install

isitright needs Python 3.11 or newer.

```console
python -m pip install isitright                 # the core and SQLite
python -m pip install "isitright[mcp]"          # + the agent pack (MCP), and the research pack's stdio server
python -m pip install "isitright[postgres]"     # + native PostgreSQL on a disposable local server
python -m pip install "isitright[duckdb]"       # + DuckDB, as labeled emulation of PostgreSQL
python -m pip install "isitright[bigquery]"     # + BigQuery client, to confirm findings (NOT in [all])
python -m pip install "isitright[trino]"        # + Trino client, to confirm findings (NOT in [all])
python -m pip install "isitright[all]"          # all of the above except bigquery and trino
```

The research pack runs with the base install: stand-in agents, agents given as code and recorded
runs need no extra. Only an agent command that talks to the corpus tools over MCP needs `[mcp]`.

`isitright[all]` does **not** include `bigquery` or `trino`. Those two extras install a cloud
client (about thirty packages for BigQuery) that you need only to confirm a finding on your own
engine, so you install them on purpose: `pip install "isitright[bigquery]"` or
`pip install "isitright[trino]"`. Searching and reporting for BigQuery, Presto and Trino
queries needs neither.

Check the install:

```console
isitright --version
isitright --help
```

| Extra | Adds | You need it when |
|---|---|---|
| none | SQLite engine, the core, the report model | Your queries target SQLite |
| `mcp` | The MCP SDK | You audit an agent, or run any `agents` command |
| `postgres` | A disposable local PostgreSQL server and `psycopg` | Your queries target PostgreSQL |
| `duckdb` | DuckDB | You want a fast PostgreSQL candidate generator, or you audit BigQuery, Presto or Trino queries. Its findings are [emulated](../concepts/validity-and-fidelity.md) |
| `data` | pandas and `psutil` | You audit an agent that writes Python over data files. `psutil` enforces the memory limit on Linux and macOS |

## The examples live in the repository

The quick starts use files from `examples/`, which the wheel does not ship. Clone the repository:

```console
git clone https://github.com/isitright-ai/isitright.git
cd isitright
python -m pip install -e ".[all]"
```

From a source checkout you can also use `uv sync --locked --extra dev --extra all`.

## Choose a quick start

<div class="grid cards" markdown>

- **[SQL](sql.md)**: compare a gold and a generated query on perturbed databases. Takes about two
  minutes and needs no network or API key.
- **[Agents](agents.md)**: audit a tool-using agent over MCP with scripted stand-ins. Takes a few
  minutes and needs no API key.
- **[Research](research.md)**: audit a research agent that answers from a frozen corpus, with a
  stand-in agent. Needs no API key.
- **[Data analysis](data.md)**: audit two recorded programs against a small data task, offline.
  Needs the `data` extra and no API key.
- **[BigQuery and Presto/Trino](warehouses.md)**: audit queries written for a warehouse from a table
  definition alone, with no account. Needs the `duckdb` extra.

</div>

Both quick starts run offline. Nothing in isitright's core calls a model or needs a key; the
optional LLM-assisted steps in [Onboarding with an LLM](../onboarding/index.md) are separate and
labeled.

## Platform notes

The agent pack is developed and tested mainly on Windows, with Linux in CI. On Windows the timeout
kill uses `taskkill /T`; elsewhere it kills a process group. Shell examples in these docs use
POSIX syntax for environment variables; in PowerShell write `$env:NAME = "value"` first.
