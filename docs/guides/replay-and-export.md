# Replay and export

Both packs write a replayable artifact with each finding and can export findings as new eval cases.
A one-time audit becomes a growing regression suite.

## Replay

Replay checks that a finding reproduces, from the report alone.

=== "SQL"

    ```console
    isitright sql replay artifacts/quick-start/case_report.json
    ```

    ```text
    Reproduced both query outputs on sqlite 3.53.1.
    ```

    Replay rebuilds the schema and the concrete [minimized](../concepts/minimization-and-replay.md) rows from `replay.json` on the recorded
    engine and compares both outputs. Report-provided SQL is **never** executed as state. Each
    recorded query runs under a 30-second deadline and a 10,000-row cap (`--timeout`,
    `--max-result-rows`).

    `counterexample.sql` is a hand-readable version of the same world. A hand-edited SQLite fixture
    can be replayed with `python -m isitright.packs.sql.fixture_replay --report R --fixture F`, under
    an authorizer that denies `ATTACH`, triggers, extension loading and other PRAGMAs.

=== "Agents"

    ```console
    isitright agents replay --report artifacts/shop/report.json --trust-code [--findings-only]
    ```

    Replay works on the **recorded** runs offline: it does not call your agent. It rebuilds the
    world, re-executes the recorded calls against the simulated service, and checks that the final
    state and the verdicts match.

    ```text
    g796c4bc4_edge_value+timing/1: reproduced. 5 calls re-executed; state and verdicts match
    ```

    `--findings-only` replays only runs behind a finding. It needs `--trust-code` because it loads
    the [scenario](../agents/write-a-scenario.md). For a [third-party server](../agents/external-servers.md), replay re-judges the
    recorded state and trace instead of re-executing the calls.

Replay works from the concrete minimized world, not from a random seed, so it is stable across
versions of the search.

## Export

```console
isitright sql export artifacts/quick-start/case_report.json --output evals/generated.jsonl
isitright agents export artifacts/shop/report.json --output evals/shop-generated.jsonl
```

The output file is **appended** to, one JSON object per line. Each line is an `EvalCase`:

| Field | Contents |
|---|---|
| `pack` | `sql` or `mcp` |
| `case_id` | Stable id for the new case |
| `source_finding` | The finding it came from |
| `payload` | SQL: a fixture state, both queries and the comparison policy. Agents: the world, the task, the recorded trace |
| `expectation` | SQL: the two outputs and that they differ. Agents: the verdict |

`rerun_eval_case` rebuilds a case and checks it still behaves as recorded: for SQL it rebuilds the
state and checks the queries still disagree; for agents it replays the trace offline and re-judges.
Both are plain functions that return a result dict:

```python
from isitright.core.evidence import EvalCase
from isitright.packs.sql.replaying import rerun_eval_case          # SQL
# from isitright.packs.mcp.replay import rerun_eval_case           # agents (takes the scenario too)

import json
for line in open("evals/generated.jsonl", encoding="utf-8"):
    print(rerun_eval_case(EvalCase.model_validate(json.loads(line))))
```

## What to do with an exported case

An exported case records a **disagreement**, not a decision. Before adding it to your eval set:

1. Decide which side is wrong, using [Reviewing findings](../onboarding/triage.md).
2. If the reference was wrong, fix the gold query and add the world as a case that the fixed
   reference passes.
3. If the candidate was wrong, add the case as a regression test for your model.

An exported case adds no new knowledge about which side was right.
