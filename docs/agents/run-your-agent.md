# Run your agent

The agent is **any command** that can run your agent on a task, given an MCP configuration that
points at the world's server. isitright does not care what framework is inside.

```console
isitright agents run --trust-code --scenario my_scenario.py:SCENARIO \
  --agent-command "python my_agent.py --config {mcp_config} --task {task_file}"
```

## The contract

For every run, isitright creates a run directory (`runs/<world>/<trial>/`) and starts the command in
it. Your command must:

1. **Read the task** from the file named by `ISITRIGHT_TASK_FILE` (or `{task_file}`).
2. **Connect to the world's MCP server** using the config named by `ISITRIGHT_MCP_CONFIG` (or
   `{mcp_config}`), a standard `mcpServers` document with one stdio server named `isitright`.
3. **Do the task**, then exit. Exit code `0` is a completed run. Any other code is `SUBJECT_ERROR`.
4. Optionally **write `transcript.json`** into `ISITRIGHT_RUN_DIR` with the stack and the cost.

The placeholders `{mcp_config}`, `{task_file}` and `{run_dir}` are substituted into the command's
arguments. The same values are exported as `ISITRIGHT_MCP_CONFIG`, `ISITRIGHT_TASK_FILE`,
`ISITRIGHT_RUN_DIR` and `ISITRIGHT_WORLD` (the world's id).

`mcp.json` looks like this:

```json
{
  "mcpServers": {
    "isitright": {
      "command": "/path/to/python",
      "args": ["-m", "isitright.packs.mcp.serve", "--scenario", "my_scenario.py:SCENARIO",
               "--fixed", "original", "--run-dir", "runs/original/1", "--trust-code"]
    }
  }
}
```

The arguments differ per world (this one is a fixed world); do not parse them. Treat the file as the
connection details for one stdio server.

Hand this configuration to your agent framework as-is. Most MCP-capable agent SDKs accept an
`mcpServers` document or the equivalent command and arguments for a stdio server. The scripted agent
`examples/agents/demo_agent.py` is the smallest complete client, and
`examples/agents/tau2_openai/run_agent.py` is a real adapter for the OpenAI Agents SDK with a user
simulator.

If your agent is not MCP-native, write a small shim that exposes the server's tools to it. A prompt
for generating that shim is in [Agent setup](../onboarding/agents.md#wrap-your-agent).

## What a run records

| File | Written by | Contents |
|---|---|---|
| `mcp.json`, `task.txt`, `world.json` | runner | The config, the task text, and the world (state, response edits, timers) |
| `trace.jsonl` | server | Every tool call: arguments, result, error flag |
| `state_before.json`, `state_after.json` | server | The service state at the start and the end, hidden from the agent |
| `agent.log` | runner | The agent's stdout and stderr |
| `transcript.json` | your agent (optional) | `provider`, `model`, `sdk_versions`, `settings`, `stop_reason`, `usage` |

`agent.log` is the first place to look when a run shows `E`, "did not complete".

## Reporting the stack and the cost

`transcript.json` lets the report name the stack under test and lets `--max-money` work:

```json
{
  "provider": "openai",
  "model": "gpt-5-mini",
  "sdk_versions": {"openai-agents": "0.4.0"},
  "settings": {"temperature": 0},
  "stop_reason": "end_turn",
  "usage": [
    {"input_tokens": 1200, "output_tokens": 180, "cost": 0.0021},
    {"input_tokens": 1500, "output_tokens": 90, "cost": 0.0023}
  ]
}
```

`usage` has one entry per model call. **`--max-money` needs a `cost` in every entry.** If a completed
run does not state one, the run is refused with exit code 2 after the first run, instead of running
unbounded. For an agent that does not report cost, use `--max-runs` or `--max-seconds`.

If a simulated user is itself a model, add `user_usage` with the same entries. The runner records the
user's calls and tokens apart from the agent's, and `money` (what `--max-money` counts) is the
agent's cost plus the user's.

## Timeouts and failure

`--timeout` (seconds per run, default 300) kills the agent and its server, and the run is `TIMEOUT`.
A run that did not complete is reported `E`, counted, and skipped when pairing with the [baseline](../concepts/live-agents.md#baseline-first).
It is never scored as a pass or a failure of the agent.

## Environment

- Agents start with one thread each for OpenBLAS, OpenMP and MKL (`OPENBLAS_NUM_THREADS`,
  `OMP_NUM_THREADS`, `MKL_NUM_THREADS`) unless your environment sets them. Several agent processes
  with a server that imports numpy could not start on a small machine otherwise.
- The agent command runs with **your permissions and network**. isitright does not sandbox it. Do not
  point a live agent at tools that can reach real systems; the [scenario](write-a-scenario.md)'s server is the only thing
  it should be able to change.
- Credentials are read from your environment by your agent. isitright never writes them to reports.

## Conversations with a user

For tasks where a user model drives the conversation, your command runs the conversation. The tau2
example does this and reports `user_usage`. It ends a conversation the user stopped right after the
agent's question as a run that did not complete (the agent command exits with code 3;
`--accept-unanswered-stop` keeps the old behavior) and passes `max_turns` (default 30, `ISITRIGHT_AGENT_MAX_TURNS`) to the SDK.
