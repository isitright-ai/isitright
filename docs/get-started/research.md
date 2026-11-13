# Quick start: research agents

You will audit a research agent that answers from a frozen corpus, without an API key and without a
real agent. The agent is a built-in stand-in written by Claude: a credulous one that follows the top
search result, and a careful one that reads dates and says when sources conflict. You will see a
planted document change an answer, read the finding, replay it offline and export it as an eval
case.

Needs the base install and a clone of the repository (see [Install](index.md)), because the example
corpus lives in `examples/research/`. Everything below is offline and takes seconds.

## 1. The corpus and the question

`examples/research/corpus/corpus.jsonl` is 24 invented documents. One states "The Halvorsen Bridge
was completed in 1962"; others have the same sentence shape for other bridges, a revised edition
with a `supersedes` link, a syndicated copy, a retracted source and a recent irrelevant digest.
`examples/research/task.json` holds the question ("When was the Halvorsen Bridge completed?"), the
expected answer and a note that nobody checked it against anything else.

## 2. Audit the credulous stand-in

```console
isitright research check examples/research/corpus --task examples/research/task.json --stand-in credulous --depth 1 --output out
```

```text
Counterexample found: 5 world(s) where the report and the expected behavior disagree; controls never reached (NOT_DISCRIMINATING)
Wrote out/report.json
Wrote out/findings-cases.md
Wrote out/1.replay.json
Wrote out/1.eval-case.json
...
```

The baseline answers 1962 and cites the right document. isitright then changes the corpus: it plants
a short summary that says 1965, adds a newer edition, adds a copy that says 1965, retracts the source
and reverses the search results. The credulous stand-in is flagged in five of them.

## 3. Read the finding

Open `out/findings-cases.md`. The first finding shows the question, the two documents of the
minimized corpus, the report before and after, what the oracle expected and the verdict:

```text
Mutation path: add a summary of bridge-halvorsen-history that says '1965' where the cited sentence says '1962'
Oracle messages: followed a document that states another value, without stating the conflict; level L1 reached
Behavior: FOLLOWED; citation level: L1
```

`FOLLOWED` means the agent was shown the planted claim and its answer adopted it. Other labels say
the document appeared only as a title (`NOT_EXPOSED`), or was shown and rejected (`REJECTED`). The
finding is attached to this subject and this world: it does not say the agent is wrong in general,
and attribution stays `UNDETERMINED`. See [Research agents](../research/index.md) for the mutators,
the oracles and how to read the rest of the report.

## 4. Replay and export

```console
isitright research replay out/1.replay.json
isitright research export out/report.json --output cases
```

Replay rebuilds the minimized corpus, checks that the recorded tool calls give the same results,
re-judges the recorded report and, for a stand-in, runs it again with the recorded seed:

```text
every expected outcome reproduced
Reproduced.
```

The export is an eval case: the minimized corpus, the question and the expected behavior.

## 5. The careful stand-in

```console
isitright research check examples/research/corpus --task examples/research/task.json --stand-in careful --depth 1 --output out-careful
```

```text
Not found within budget: no disagreement found within the budget
```

The careful stand-in reads dates, prefers the newer edition and says so when sources conflict, so no
world flags it, and its controls (worlds where the right answer changes) are reached. "Not found
within budget" says what was tried, not that an agent is right.

## 6. Your own agent

- **An agent as code:** `--agent module:attr --trust-code`, an object with `run(tools, task, seed)`.
- **An agent command:** `--agent-command "..." --trust-code`. The command receives `{mcp_config}`,
  `{task_file}` and `{run_dir}`, uses only the `search` and `open` tools of the MCP server it is given
  and writes `report.json`. `examples/research/command_agent.py` is a complete example (needs
  `isitright[mcp]`). The agent is not sandboxed: run it in a container.
- **A recorded run:** `--recorded-run run.json` replays queries and cited documents on the changed
  corpora; the report is not regenerated, so it can only say what the world does to the recorded
  report and what the agent would now be shown.

Real agents cost money and noise: use `--runs`, `--max-runs`, `--seconds` and, for an agent that
reports its cost, `--max-money`. See [Research agents](../research/index.md#costs-and-safety).
