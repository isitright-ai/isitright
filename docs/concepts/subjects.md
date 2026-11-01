# Subjects

The **subject** is the thing isitright is testing. What kind of subject it is decides how many times
it runs per world and what kind of claim a finding can support.

| Subject kind | What is under test | Runs per world | What a finding says |
|---|---|---|---|
| `ARTIFACT` | A static program the agent produced, such as a generated SQL query | One. It is deterministic | "This query returns a different answer than the reference on this valid database" |
| `AGENT` | The live agent, placed in the changed world | Several | Individual observed failures, or a comparison of failure rates against the unchanged world |
| `FROZEN_ARTIFACT` | A program extracted from one live run, then tested across many worlds | One | Reserved for a later pack. The claim would be "this program is wrong on world X", not "this agent is" |

## Which one am I using?

- **Text-to-SQL:** your candidate query is an `ARTIFACT`. isitright re-runs the *query* on each changed
  database. It does not re-run the model that wrote it, so a finding is about that query, not about
  how the model would answer on a different database.
- **Tool-using agents over MCP:** your agent is an `AGENT`. It runs live in each changed world. It
  sees the changed world and may behave differently, which is the point, and which is also why runs
  repeat and results are counted rather than judged once.

This difference matters when you read a SQL finding. If the changed world would have led the model to
write a *different* query, the finding does not say the model fails there. It says the query it wrote
for the original world is not robust to that change.

## Costs and noise

An `ARTIFACT` costs milliseconds per world, so isitright can try hundreds of worlds. An `AGENT` costs
seconds and money per run and can pass and fail on the same world, so isitright runs a [baseline](live-agents.md#baseline-first),
repeats runs, and ranks worlds so the expensive runs go to the likeliest ones. See
[Live agents](live-agents.md).
