# Evidence: reading an audit report

An audit report answers one question per eval case: *did isitright find a valid world where this pass
stops holding, and how far should I trust that?* This page explains every part of the answer. The
short version is on the [home page](../index.md#what-you-get-back).

## What is being compared

On every changed world isitright runs two things:

- the **[subject](subjects.md)**: your generated query, or your live agent;
- the **[oracle](oracles-and-roles.md)**: a reference that recomputes what is right *for that world*. For SQL it is your gold
  query, re-run on the changed database. For an agent it is a reference procedure plus invariants
  you wrote. See [Oracles and roles](oracles-and-roles.md).

A **divergence** is a world where the subject and the oracle disagree. That is all the word means.
The unchanged world is *not* the reference: on the unchanged world they already agree, because that
is why the eval passes.

## Seven fields, kept apart

A report keeps these separate because merging them is how audits overclaim. Read them in this order.

| Field | The question it answers |
|---|---|
| `divergence_status` | Did they disagree on some world? |
| `validity` | Could that world exist? |
| `execution_fidelity` | Where did the outputs come from, and how real is that? |
| `oracles` | Who decided what was right, and could it decide? |
| `stability` | For an agent: how often did it fail, compared with the unchanged world? |
| `subject_kind` | What was tested: a fixed query or a live agent? |
| `attribution_status` | Which side is wrong? |

The `headline` is one line derived from them. It never says "pass", "fail", "correct" or "wrong".

### `divergence_status`

| Status | What it means | What to do |
|---|---|---|
| `COUNTEREXAMPLE_FOUND` | On a valid changed world, the subject and the oracle disagree | Read the finding. Check validity and [fidelity](validity-and-fidelity.md#execution-fidelity), then decide which side is wrong |
| `NOT_FOUND_WITHIN_BUDGET` | None of the worlds tried produced a disagreement | Look at how many worlds ran and which families were skipped. This is not a claim of correctness or equivalence |
| `INCONCLUSIVE` | The comparison could not decide. Typical causes: result order is ambiguous, no agent run completed, a result was nondeterministic | Read the reason in the report and fix the cause |
| `UNSUPPORTED` | The input is outside what isitright handles, for example an unsupported SQL construct | Rewrite the input or accept that it is not covered. It is rejected, never weakened |

### `validity`: could that world exist?

A counterexample in an absurd world is not worth acting on. `validity` lists the checks the world
passed, from weakest to strongest:

- [`STRUCTURAL`](validity-and-fidelity.md#validity-tiers): the database or service accepts it (keys, types, references hold).
- `DOMAIN_VALIDATED`: it also obeys every domain rule *you gave isitright*.
- `REACHABLE`, `TASK_CONSISTENT`, `OBSERVABLE`: for agents, the state can arise through the service's
  own operations, the task's story still makes sense, and the agent could see the change through some
  tool.

`DOMAIN_VALIDATED` means "passed the rules provided", not "realistic". A world is only as believable
as your rules. [Validity and fidelity](validity-and-fidelity.md) has the full table.

### `execution_fidelity`: where did the outputs come from?

| Value | Meaning |
|---|---|
| `NATIVE_ISOLATED` | The real engine (or your real service code) on a disposable copy |
| `EMULATED` | A different engine ran translated SQL (DuckDB standing in for PostgreSQL). Treat as a candidate until it says `verified_on: NATIVE_ISOLATED` |
| `SIMULATED` | Handlers you wrote stand in for the service. The finding is about your stand-in |

### `stability`: for live agents

Agents are not deterministic, so one failure proves little. The report counts, for example: *"failed in 6 of 8 runs
here, 0 of 4 on the unchanged world"*. Only when a statistical test decides (`RATE_INCREASE`) does
the report claim that the change raises the failure rate. Otherwise you have observed failures, which
are facts about those runs. See [Live agents](live-agents.md).

### `attribution_status`

Always `UNDETERMINED` until a human decides. A disagreement does not show which side is wrong: gold
queries and reference procedures are implementations too, and errors in them are common. Values you
can record once you have decided: `AGENT_DEFECT`, `REFERENCE_DEFECT`, `AMBIGUOUS_TASK`,
`POLICY_AMBIGUOUS`, `TOOL_CONTRACT_AMBIGUOUS`, `SIMULATOR_DEFECT`. See
[Reviewing findings](../onboarding/triage.md).

## A finding, read once

This is the SQL quick start's finding, in the order to read it:

```text
Divergence status      COUNTEREXAMPLE_FOUND          they disagree on a world
Validity               STRUCTURAL, DOMAIN_VALIDATED  the world obeys the schema and my rules
Execution fidelity     NATIVE_ISOLATED (sqlite)      real SQLite, on a copy
Review classification  UNDETERMINED                  I have to decide who is wrong
Triggering change      a copy of tribute[1] is added with amount_collected = NULL
Minimized rows         4 to 2
```

Reading it: *on a valid world that differs from mine by one NULL, the two queries return 70 and 170;
the world is small enough to read; nobody has said which is right.* The next step is yours.

## How strong is this finding?

Ask in this order:

1. **Fidelity.** Native, or verified natively? An unverified `EMULATED` finding never fails CI.
2. **Validity.** `DOMAIN_VALIDATED` means your rules held. `STRUCTURAL` only means the engine accepts
   it, and a domain expert may still call it absurd.
3. **Oracle.** Is the reference one you trust, and did its own assumptions cover this world?
4. **Stability** (agents). Counts against the [baseline](live-agents.md#baseline-first). A rate claim names its test and decision.
5. **Observability** (agents). Could the agent see the change? If not, the finding is about your tool
   contract, not the agent.

Suite reports rank cases by this, strongest first: domain-validated counterexamples, structural-only,
inconclusive or unsupported, not found.

## Not found is not correct

`NOT_FOUND_WITHIN_BUDGET` means isitright tried what its budget allowed and saw no disagreement. The
report says what that was: attempts, worlds run, worlds skipped, families run and skipped. For live
agents it also lists worlds it never reached as `NOT_RUN`. Read those numbers before relying on a
clean result.

The complete field list is in the [report schema reference](../reference/report.md).
