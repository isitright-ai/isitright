# Report schema

One versioned JSON schema covers both packs: [`schemas/report-0.5.schema.json`](https://github.com/isitright-ai/isitright/blob/main/schemas/report-0.5.schema.json),
exported from `isitright.core.evidence.AuditReport` by `tools/export_schemas.py`. Pack-specific
detail lives under `extensions` and is not part of the common contract.

What scripts, CI and other tools may rely on is what this page lists. Anything else may change
between pre-1.0 releases.

## Compatibility

Schema `0.5` replaces `0.4`. Reports written as `0.4` still load: `replay` and `export` read them,
because every field added in 0.5 is optional. Older schemas are removed.

## AuditReport

| Field | Contents |
|---|---|
| `schema_version` | `"0.5"` (`"0.4"` when read from an older report) |
| `pack` | `sql` or `mcp` |
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
| `extensions` | `sql`, `mcp`: pack-specific fields, not part of the common contract |

### Invariants the model enforces

- The status and the findings must agree.
- An `UNSUPPORTED` case has no executed worlds.
- A DuckDB result must be labeled `EMULATED`; a PostgreSQL or SQLite one must not.
- `NOT_FOUND_WITHIN_BUDGET` means no disagreement was found within the budget. It is never a claim of
  equivalence or correctness.
- A world that screening or a stopping rule did not run is `NOT_RUN`, never a pass.
- An observed failure is never presented as a rate change, and an emulated finding is never
  presented as native: `verified_on` says whether PostgreSQL confirmed it.

### Screening classes

`WRONG_IF_UNCHANGED`, `STALE`, `RIGHT_IF_UNCHANGED`, `UNSCREENABLE`. See [Live agents](../concepts/live-agents.md).

### Sequential decisions

`RATE_INCREASE`, `NO_INCREASE_AT_EFFECT`, `UNDECIDED`, `NO_DISCORDANCE`.

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
