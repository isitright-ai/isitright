# Install

isitright needs Python 3.11 or newer.

```console
python -m pip install isitright                 # the core and SQLite
python -m pip install "isitright[mcp]"          # + the agent pack (MCP)
python -m pip install "isitright[postgres]"     # + native PostgreSQL on a disposable local server
python -m pip install "isitright[duckdb]"       # + DuckDB, as labeled emulation of PostgreSQL
python -m pip install "isitright[all]"
```

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
| `duckdb` | DuckDB | You want a fast PostgreSQL candidate generator. Its findings are [emulated](../concepts/validity-and-fidelity.md) |

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

</div>

Both quick starts run offline. Nothing in isitright's core calls a model or needs a key; the
optional LLM-assisted steps in [Onboarding with an LLM](../onboarding/index.md) are separate and
labeled.

## Platform notes

The agent pack is developed and tested mainly on Windows, with Linux in CI. On Windows the timeout
kill uses `taskkill /T`; elsewhere it kills a process group. Shell examples in these docs use
POSIX syntax for environment variables; in PowerShell write `$env:NAME = "value"` first.
