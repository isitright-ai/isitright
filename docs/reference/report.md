# Report schema

One versioned JSON schema covers all packs: [`schemas/report-0.9.schema.json`](https://github.com/isitright-ai/isitright/blob/main/schemas/report-0.9.schema.json),
exported from `isitright.core.evidence.AuditReport` by `tools/export_schemas.py`. Pack-specific
detail lives under `extensions` and is not part of the common contract.

What scripts, CI and other tools may rely on is what this page lists. Anything else may change
between pre-1.0 releases.

## Compatibility

Schema `0.9` replaces `0.8`. Reports written as `0.4`, `0.5`, `0.6` or `0.8` still load: `replay` and
`export` read them, because every field added since is optional. Older schemas are removed.
0.9 adds four counts to `stability.sequential` (`world_runs`, `baseline_runs`, `excluded_errored`,
`excluded_unjudged`, default 0, so older reports load), `findings[].world_fingerprint` and
`findings[].built_from` (see [One world per finding](#one-world-per-finding); both default to empty, so
older reports load) and the run loop's change of meaning for the test: every pair is a run of the world and a fresh baseline run (see
[live agents](../concepts/live-agents.md#sequential-testing-per-world)). A 0.8 report keeps its old
meaning: the research and data packs paired against baseline runs they had, or assumed. 0.6 added `findings[].mode`
(`frozen_program` or `live_agent`) and `findings[].live` (see below). 0.8 adds the mode `frozen_trace`
(a recorded research run replayed, its report not regenerated) and `schema_version` `"0.8"`; the research
pack's other fields are under `extensions.research` (see below).

## AuditReport

| Field | Contents |
|---|---|
| `schema_version` | `"0.9"` (`"0.4"`, `"0.5"`, `"0.6"` or `"0.8"` when read from an older report) |
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
| `divergence_status` | [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status), `OBSERVED_FAILURE` (0.9, live agents), `NOT_FOUND_WITHIN_BUDGET`, `INCONCLUSIVE`, `UNSUPPORTED` |
| `validity` | `status`: `VALID`, `INVALID`, `INDETERMINATE`, `NOT_ASSESSED`. `tiers`: [`STRUCTURAL`](../concepts/validity-and-fidelity.md#validity-tiers), `DOMAIN_VALIDATED`, `REACHABLE`, `TASK_CONSISTENT`, `OBSERVABLE`, `SIMULATOR_CONSISTENT` |
| `execution_fidelity` | `found_on`: [`NATIVE_ISOLATED`](../concepts/validity-and-fidelity.md#execution-fidelity), `NATIVE_INLINE`, `EMULATED`, `SIMULATED`, `GENERATED`, `REPLAY_ONLY`. `verified_on`: `NATIVE_ISOLATED` once an emulated finding is re-executed on PostgreSQL. `engine`. `verification`: `VERIFIED`, `EMULATION_ARTIFACT` or `NOT_VERIFIED`, with a note |
| `oracles` | `name`, `kind` (`REFERENCE_PROGRAM`, `INVARIANT`, `RELATIONAL`, `CONSTRUCTIVE`, `JUDGE`), `outcome` (`MET`, `NOT_MET`, `CANNOT_JUDGE`), `limits` |
| `subject_kind` | `ARTIFACT`, `FROZEN_ARTIFACT`, `AGENT` |
| `stability` | `k`; baseline and world `counts`; `rate_claim` (test, pair counts, p-value) only with adequate evidence; `sequential` (test, alpha, beta, boundaries, every look, decision, and how the pairs were made: `world_runs`, `baseline_runs`, `excluded_errored`, `excluded_unjudged`) |
| `attribution_status` | `UNDETERMINED` by default; reserved: `AGENT_DEFECT`, `REFERENCE_DEFECT`, `AMBIGUOUS_TASK`, `POLICY_AMBIGUOUS`, `TOOL_CONTRACT_AMBIGUOUS`, `SIMULATOR_DEFECT` |
| `search` | Seed, attempts, valid candidates, executed, rejections by reason, families run and skipped, budget per [hint](../concepts/hints.md) group (`hinted`, `unhinted`), hints used, depth reached, budget, `screening`, `stopping`, `hint_use` |
| `multiplicity` | 0.9, live agents: `worlds_tested`, `worlds_with_observed_failure`, `worlds_with_rate_increase`, `alpha`, `decisions_corrected` (always false), `expected_rate_increase_claims_under_no_effect` (`worlds_tested x alpha`: a nominal upper bound on the expected false rate-increase claims under no effect, not a measured rate and not a family-wise guarantee), `expected_worlds_with_observed_failure_under_no_effect` (from the baseline's observed rate; null when no baseline run was judged) and a note |
| `findings` | Per finding: `evidence_grade` (0.9, live stochastic agents: `RATE_INCREASE` or `OBSERVED_FAILURE`; null for frozen programs and reports, deterministic subjects and SQL), `observation` (0.9: `world` and `baseline` each with `failures`, `judged`, `errors`, `unjudged`, `rate` and a 95% Wilson interval, descriptive), world, validity, [oracle](../concepts/oracles-and-roles.md) results, stability, world diff, mutation path (family, target, description, hints, atoms), pack-specific `divergence`, fidelity, replay, minimization |
| `worlds`, `controls` | Every world run and the best-ranked worlds not run, with role, counts, screening class and rank, `run_status` (`RUN` or `NOT_RUN` with the reason) and validity `notes`. `controls`: `DISCRIMINATING`, `NOT_DISCRIMINATING` or `NOT_APPLICABLE` |
| `headline` | One line derived from the above. It never says pass, fail, correct or wrong; the model rejects it |
| `extensions` | `sql`, `mcp`, `data`: pack-specific fields, not part of the common contract |

### Invariants the model enforces

- The status and the findings must agree: `COUNTEREXAMPLE_FOUND` holds exactly when some finding is not graded `OBSERVED_FAILURE`; `OBSERVED_FAILURE` holds exactly when there are findings and all are.
- A `RATE_INCREASE` grade is set only from a paired sequential test that crossed its upper boundary: the finding must carry a sequential record whose decision is `RATE_INCREASE` and a rate claim that agrees with it. An `OBSERVED_FAILURE` finding carries no such decision or claim and records at least one judged failure in its `observation`. A report that breaks either rule is refused when it is loaded. Findings with no grade (frozen programs and reports, deterministic subjects, SQL, legacy reports) need none of this.
- A world whose validity was not assessed (a fixed MCP world with no validator) keeps `validity.status: NOT_ASSESSED` with no tier, in its finding, its `worlds` entry and the case. A grade says nothing about validation: a `RATE_INCREASE` on such a world is conditional on the world as run.
- Suite and case ranking (`rank_cases`), strongest first: domain-validated `COUNTEREXAMPLE_FOUND`; structurally validated; other `COUNTEREXAMPLE_FOUND` (including an unassessed validity); `OBSERVED_FAILURE`; `INCONCLUSIVE` and `UNSUPPORTED`; `NOT_FOUND_WITHIN_BUDGET`. Equal strengths keep their order.
- A finding that names a `world_fingerprint` is about that one world, and the model refuses a finding whose parts disagree (see [One world per finding](#one-world-per-finding)).
- An `UNSUPPORTED` case has no executed worlds.
- A DuckDB result must be labeled `EMULATED`; a PostgreSQL or SQLite one must not.
- `NOT_FOUND_WITHIN_BUDGET` means no disagreement was found within the budget. It is never a claim of
  equivalence or correctness.
- A world that screening or a stopping rule did not run is `NOT_RUN`, never a pass.
- An observed failure is never presented as a rate change, and an emulated finding is never
  presented as native: `verified_on` says whether PostgreSQL confirmed it.

### One world per finding

A finding reports one world. `world_fingerprint` is the fingerprint of that world (`World.fingerprint`:
its state, response edits and timers; the mutation path is a record of how it was made and is not part
of it). `built_from` maps each part of the finding that describes a world to the fingerprint of the
world that part was built from: `validity`, `world_diff`, `divergence` (the outputs and the
reproduction result), `counts` (when the finding has run counts), `replay` (when it names a replay
artifact) and `export` (when it names an eval case). Replay and export entries are taken from the
world stored in the artifact itself. The model enforces that:

- every finding of a report with `schema_version` `0.9` has a non-empty `world_fingerprint`; a 0.9
  report without one is refused. A finding that names a world is checked whatever the report's
  version;
- every `built_from` entry equals `world_fingerprint`; a finding whose parts name different worlds is
  refused when it is built or loaded, naming the parts;
- `validity`, `world_diff` and `divergence` are always tied to the world, and so are `counts`
  (when the finding has an `observation` or `stability`), `replay` and `export` when it has them;
- a finding that names a world does not carry `divergence.reproduces` or
  `divergence.reproduces_on_shown_world` set to false: a world that does not reproduce is not shown;
- a finding graded `RATE_INCREASE` has a paired decision of `RATE_INCREASE` whose pairs are runs of
  the world shown: the finding's `observation.world` has at least as many judged runs as the test has
  pairs. The grade is never carried from another world.

Reports written as `0.8` or earlier carry no fingerprint and load as they always did, including
findings with the older divergence fields. A stamp written by the code that built a finding is not
proof that an artifact holds that world, so wherever the artifact and the finding are both at hand the
world stored in the artifact is compared with `world_fingerprint`: when the data and research packs
write their replay artifacts, in `data replay`, in `agents export` and in `agents replay` (against
the world the run was launched with). The packs choose the
world to show as follows. A SQL finding shows the minimized world when it reproduces a disagreement of
the kind that was found (an error, a different row count, or different values with the same count);
otherwise it shows the world the search found. For a warehouse, if only the larger world differs on
the native engine, that is the world shown, `fidelity.verified_on` describes it, and the minimized
world is attached as `divergence.minimized_world` with `fidelity: EMULATED` and `verified: false`.
`minimization.shown` says which world is shown (`minimized` or `unminimized`), and `minimization.reason`
why it is the larger one. A minimized SQL world is kept only if its difference has the kind of the one
found, by this precedence: `error` (the candidate errors and the reference does not), else
`row_count` (the row counts differ, whatever the columns do), else `row_values` (values or columns
differ). If the reference itself errors there is no kind, and no finding. Keeping the kind is a coarse
safeguard, not proof that minimization kept the same root cause. When neither the minimized nor the found
world reproduces a difference of that kind on a rerun, there is no finding: the case is `INCONCLUSIVE`
with the error code `NOT_REPRODUCED`. An agents finding shows the minimal mutation path only when that path, run
as a world of its own, fails at least as strongly as the searched world; the research pack applies
the same rule, and records a minimized world that is not shown under `minimization.not_adopted`.

### Which mutations a finding names

`mutation_path` lists the mutations with a demonstrable effect in the world the finding shows (SQL,
frozen data, deterministic and frozen research). An edit counts when it is still in effect: a row it
added is present, a row it removed is absent, a field it set holds the value it assigned and differs
from the base, a field it unset is absent, a parameter holds its value, and no later edit that is
itself in effect overwrote it (mutation A sets `v = 1`, B sets `v = 2`, the world has `v = 2`: only B
is named). A response or timing mutation is named while its response edit or timer is in the shown
world. A mutation with no traceable edits is not named: nothing shows an effect.

The path that produced the world the search found is kept apart, as provenance, under
`minimization`: `searched_path` (family, target and description of each mutation),
`provenance_only: true` (it is not a replay recipe: the shown world may be a minimization that no
replay of that path reconstructs; replay and export use the shown world) and `mutation_attribution`:
`SURVIVING_EDITS`, `UNDETERMINED` (the world differs from the base but no searched mutation has a
surviving effect, for example because minimization removed the rows it edited and the world differs
by an absence) or `NONE` (no mutation produced the world). With an empty `mutation_path` and a
non-empty `world_diff` the headline describes the change that is left ("on a world that differs from
the base in 1 removed (which mutation caused it is undetermined)"), never a mutation and never the
baseline.

`totals.by_family` counts each distinct family in `mutation_path` once per finding. A finding with
two surviving families counts for both, a finding with none for none, so the values can add up to
more than the number of findings. Before 0.9 only the last mutation's family was counted, so totals
of reports from before 0.9 are not comparable.

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
(`minimized`, then `unminimized divergent`) and its result; the world shown is the one the native
engine confirmed (see [One world per finding](#one-world-per-finding)). A finding's `validity.notes` says
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
