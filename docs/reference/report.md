# Report schema

One versioned JSON schema covers all packs: [`schemas/report-0.8.schema.json`](https://github.com/isitright-ai/isitright/blob/main/schemas/report-0.8.schema.json),
exported from `isitright.core.evidence.AuditReport` by `tools/export_schemas.py`. Pack-specific
detail lives under `extensions` and is not part of the common contract.

What scripts, CI and other tools may rely on is what this page lists. Anything else may change
between pre-1.0 releases.

## Compatibility

Schema `0.8` replaces `0.6` (0.7 added no field and kept 0.6). Reports written as `0.4`, `0.5` or `0.6` still load: `replay` and `export` read
them, because every field added since is optional. Older schemas are removed. 0.6 added `findings[].mode`
(`frozen_program` or `live_agent`) and `findings[].live` (see below). 0.8 adds the mode `frozen_trace`
(a recorded research run replayed, its report not regenerated) and `schema_version` `"0.8"`; the research
pack's other fields are under `extensions.research` (see below).

## AuditReport

| Field | Contents |
|---|---|
| `schema_version` | `"0.8"` (`"0.4"`, `"0.5"` or `"0.6"` when read from an older report) |
| `pack` | `sql`, `mcp`, `data` or `research` |
| `kind` | `case` (one SQL pair), `suite`, or `scenario` (one agent scenario) |
| `cases` | A list of `CaseReport` |
| `totals` | Counts per status |
| `elapsed_seconds` | |

A report from `sql check` is one `case`; from `sql suite` a `suite` of cases; from `agents run`, one
`scenario` case.

## CaseReport

Each field answers one question and is never merged with another.

| Field | Values |
|---|---|
| `divergence_status` | [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status), `NOT_FOUND_WITHIN_BUDGET`, `INCONCLUSIVE`, `UNSUPPORTED` |
| `validity` | `status`: `VALID`, `INVALID`, `INDETERMINATE`, `NOT_ASSESSED`. `tiers`: [`STRUCTURAL`](../concepts/validity-and-fidelity.md#validity-tiers), `DOMAIN_VALIDATED`, `REACHABLE`, `TASK_CONSISTENT`, `OBSERVABLE`, `SIMULATOR_CONSISTENT` |
| `execution_fidelity` | `found_on`: [`NATIVE_ISOLATED`](../concepts/validity-and-fidelity.md#execution-fidelity), `NATIVE_INLINE`, `EMULATED`, `SIMULATED`, `GENERATED`, `REPLAY_ONLY`. `verified_on`: `NATIVE_ISOLATED` once an emulated finding is re-executed on PostgreSQL. `engine`. `verification`: `VERIFIED`, `EMULATION_ARTIFACT` or `NOT_VERIFIED`, with a note |
| `oracles` | `name`, `kind` (`REFERENCE_PROGRAM`, `INVARIANT`, `RELATIONAL`, `CONSTRUCTIVE`, `JUDGE`), `outcome` (`MET`, `NOT_MET`, `CANNOT_JUDGE`), `limits` |
| `subject_kind` | `ARTIFACT`, `FROZEN_ARTIFACT`, `AGENT` |
| `stability` | `k`; baseline and world `counts`; `rate_claim` (test, pair counts, p-value) only with adequate evidence; `sequential` (test, alpha, beta, boundaries, every look, decision) |
| `attribution_status` | `UNDETERMINED` by default; reserved: `AGENT_DEFECT`, `REFERENCE_DEFECT`, `AMBIGUOUS_TASK`, `POLICY_AMBIGUOUS`, `TOOL_CONTRACT_AMBIGUOUS`, `SIMULATOR_DEFECT` |
| `search` | Seed, attempts, valid candidates, executed, rejections by reason, families run and skipped, budget per [hint](../concepts/hints.md) group (`hinted`, `unhinted`), hints used, depth reached, budget, `screening`, `stopping`, `hint_use` |
| `findings` | Per finding: world, validity, [oracle](../concepts/oracles-and-roles.md) results, stability, world diff, mutation path (family, target, description, hints, atoms), pack-specific `divergence`, fidelity, replay, minimization |
| `worlds`, `controls` | Every world run and the best-ranked worlds not run, with role, counts, screening class and rank, `run_status` (`RUN` or `NOT_RUN` with the reason) and validity `notes`. `controls`: `DISCRIMINATING`, `NOT_DISCRIMINATING` or `NOT_APPLICABLE` |
| `headline` | One line derived from the above. It never says pass, fail, correct or wrong; the model rejects it |
| `extensions` | `sql`, `mcp`, `data`: pack-specific fields, not part of the common contract |

### Invariants the model enforces

- The status and the findings must agree.
- An `UNSUPPORTED` case has no executed worlds.
- A DuckDB result must be labeled `EMULATED`; a PostgreSQL or SQLite one must not.
- `NOT_FOUND_WITHIN_BUDGET` means no disagreement was found within the budget. It is never a claim of
  equivalence or correctness.
- A world that screening or a stopping rule did not run is `NOT_RUN`, never a pass.
- An observed failure is never presented as a rate change, and an emulated finding is never
  presented as native: `verified_on` says whether PostgreSQL confirmed it.

### Frozen and live findings (0.6)

A finding found by replaying a recorded program has `mode: "frozen_program"` and is scoped to that
program. A finding from the agent's own runs has `mode: "live_agent"` and a `live` record:

| Field | Contents |
|---|---|
| `status` | `CONFIRMED`, `NOT_CONFIRMED`, `INCONCLUSIVE` |
| `runs`, `baseline_runs`, `not_met` | The agent runs made on this world and on the baseline, and the runs that disagreed with the reference |
| `agent_runs_only` | Every run counted was made by the agent, not replayed from a recording |
| `program_changed_runs` | Runs where the agent wrote code unlike its baseline code |
| `found_by_frozen_replay` | The frozen program already disagreed on this world (the world was found there and verified live) |

Fidelity records the same split: `found_on` is where the candidate was computed (`NATIVE_ISOLATED`,
the replayed program) and `verified_on` is `LIVE_AGENT` once the agent itself ran on the world.

### Screening classes

`WRONG_IF_UNCHANGED`, `STALE`, `RIGHT_IF_UNCHANGED`, `UNSCREENABLE`. See [Live agents](../concepts/live-agents.md).

### Sequential decisions

`RATE_INCREASE`, `NO_INCREASE_AT_EFFECT`, `UNDECIDED`, `NO_DISCORDANCE`.

## Warehouse reports (0.7)

0.7 added no field to the report schema; the schema stayed 0.6. Warehouse data is in
`extensions.sql`:

| Key | Content |
|---|---|
| `target_dialect` | `sqlite`, `postgres`, `bigquery`, `presto` or `trino` |
| `rewrites` | How often each exact translation fired (for example `unnest_with_offset`) |
| `template` | The `--param` values, which were used, and the original query texts |
| `native_verification` | `NATIVE_VERIFIED`, `ARTIFACTS_EXCLUDED` or `NATIVE_UNVERIFIED` |
| `emulation_artifacts` | Divergences that did not reproduce natively, with the confirmation attempts |

`comparison_policy` records `columns`, `column_vectors`, `null_as_zero`, `reference_columns` and
the tolerances. A finding's `fidelity.verified_on` is `NATIVE_INLINE` once a native host has run
both queries on the inlined state. `divergence.native_confirmation` lists each world tried
(`minimized`, then `unminimized divergent`) and its result. A finding's `validity.notes` says
when it needs equal values in a column with no declared key or unique rule. A case whose only
divergence did not reproduce natively is `INCONCLUSIVE` with no finding, and the divergence is
listed under `emulation_artifacts`.

## SQL pack output

`isitright sql check` writes `case_report.json`, `case_report.md`, `counterexample.sql` and
`replay.json`. `replay.json` is a `ReplayArtifact`: the concrete minimized rows, the schema DDL and
the expected results. Evidence for a finding includes both results, the difference, the minimized
state (`candidate_state`), a `reproducer_sql` and the mutation path. A suite adds `suite_report.json`
and `suite_report.md`, and a folder per case.

## Agent pack output

`agents run` writes `report.json`, `report.md` and `runs/<world>/<trial>/` directories (see
[Run your agent](../agents/run-your-agent.md)). `extensions.mcp.runs` holds one record per run:
status, exit code, duration, calls, writes, violations, oracle outcome, run directory, cost, and,
when the agent wrote a transcript, the stack under test.

## Eval cases

`EvalCase` is the export format: `pack`, `case_id`, `source_finding`, `payload`, `expectation`. See
[Replay and export](../guides/replay-and-export.md).

## Reading a report in code

```python
import json

report = json.load(open("artifacts/shop/report.json", encoding="utf-8"))
case = report["cases"][0]
print(case["divergence_status"], case["headline"])
for world in case["worlds"]:
    print(world["run_status"], world.get("role"))
```

Or load it into the model, which validates it:

```python
from isitright.core.evidence import AuditReport

report = AuditReport.model_validate_json(open("report.json", encoding="utf-8").read())
```

## Research reports (0.8)

Research data is in `extensions.research`:

| Key | Content |
|---|---|
| `mode` | `live` (the subject ran in each world), `frozen` (a recorded run replayed) or `baseline` (the baseline stopped the audit) |
| `subject`, `subject_statement` | Who produced the run (`stand_in`, `recorded` or `live_agent`), the name and who wrote it, and how it was used. A stand-in is always labeled |
| `retrieval` | The scorer, the document count, the tools and the fidelity (`SIMULATED`) |
| `gold` | The gold answer if one was given, and whether it was checked against anything |
| `baseline` | Runs, reports, the gate that stopped the audit if any, the citation levels reached, the queries and the opened documents |
| `flip_table` | Per mutator (or composition): worlds run, answers changed, expectations not met, unobservable changes, and the behaviors `FOLLOWED`, `NOT_RETRIEVED`, `REJECTED` |
| `unobservable_changes` | Changes no query could retrieve |
| `proposed_classification` | A proposal by the implementing assistant per finding; attribution stays `UNDETERMINED` |
| `budget` | What the run spent |

A finding's `divergence` has the question, both reports, the expected behavior, the behavior, the
citation check (`level_reached`, failures, `unquoted_citations`), whether a tie in scores decided a rank, the
documents of the shown world, the trust label of the reference, and the ids of the world the
finding was found on and of the world shown (they differ when the finding was minimized).
`world_diff` shows an edited document as a `span` (offset, removed text, inserted text).
`worlds[].screening` carries the replay class of a world (`WRONG_IF_UNCHANGED`, `STALE`,
`RIGHT_IF_UNCHANGED`, `UNSCREENABLE`) as ranking input, never a verdict.
