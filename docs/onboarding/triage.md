# Reviewing findings

A finding says the subject and the [oracle](../concepts/oracles-and-roles.md) disagree on a valid world. Someone has to decide which one
is wrong. isitright leaves `attribution_status` as `UNDETERMINED` for that reason, and this page is a
workflow for the human step. An LLM can do the first read, and you make the call.

## Checklist, in order

Each answer changes how much weight the finding carries.

1. **Is the world possible?** Read the minimized world (`counterexample.sql`, or the finding's
   `world_diff`). Could this state exist in your system? If not, a rule is missing: add a
   [domain constraint](../sql/domain-constraints.md) or a validity rule and rerun.
2. **Is the right answer clear?** Read the question or task and work out the right output in this
   world by hand. Is it unambiguous?
3. **Which side matches it?**
    - The subject (candidate query, agent) differs from the right answer: a **defect in the
      subject**.
    - The oracle (gold query, reference procedure) differs from the right answer: a **defect in the
      reference**. Gold errors are common.
    - Both are defensible: the **task or policy is ambiguous**.
4. **[Fidelity](../concepts/validity-and-fidelity.md#execution-fidelity).** Is it `NATIVE_ISOLATED` or verified natively? If `EMULATED` and unverified, rerun
   natively first. For `SIMULATED` agent runs, does your simulated tool match the real service on
   the calls in the trace?
5. **For agents: could the agent see the change?** `unobservable` means no read tool shows it. Then
   it is a tool-contract finding.
6. **For agents: how reliable?** Counts against the [baseline](../concepts/live-agents.md#baseline-first) and, if present, the `RATE_INCREASE`
   decision. A single observed violation is a fact about that run, not a rate.

The schema reserves these [attribution](../concepts/evidence.md#attribution_status) values for your decision: `AGENT_DEFECT`, `REFERENCE_DEFECT`,
`AMBIGUOUS_TASK`, `POLICY_AMBIGUOUS`, `TOOL_CONTRACT_AMBIGUOUS` and `SIMULATOR_DEFECT`.

## What to do with each outcome

| Outcome | Action |
|---|---|
| Defect in the subject | Keep the case as a regression test for your model or agent. [Export it](../guides/replay-and-export.md) |
| Defect in the reference | Fix the gold query or procedure, then re-audit. Count it: reference defects are a result of the audit |
| Ambiguous task or policy | Fix the wording, or add the world to the eval set with an explicit expected answer |
| Impossible world | Add the missing rule; rerun |
| Emulation artifact or unobservable change | Nothing to fix in the subject. Note it |

## First read with an LLM

An LLM can summarize a finding and propose which side is wrong. Treat its answer as a hypothesis.
Do not paste data you cannot share.

````text
I am reviewing a counterexample from isitright, a tool that perturbs a database or a service and
compares a candidate with a reference. Help me decide which side is wrong. Do not decide for me:
give me the reasoning I can check.

QUESTION OR TASK AND POLICY:
[paste]

REFERENCE (gold query or reference procedure):
[paste]

CANDIDATE (generated query, or the agent's recorded trace):
[paste]

THE MINIMIZED WORLD:
[paste counterexample.sql, or the world_diff and the relevant part of state_before.json]

BOTH OUTPUTS ON THAT WORLD:
[paste]

Answer in this order:
1. Work out what the correct output is in this world, step by step, from the question or policy alone.
   Do not look at the reference or candidate until you have done this.
2. Compare: does the reference match your answer? Does the candidate?
3. Name the exact expression or step where the two diverge, and what each assumes (for SQL: NULL
   handling, duplicates, join type, ties, collation. For agents: which fact the agent did not
   check, or which rule the reference applies that the policy does not state).
4. Classify: candidate defect, reference defect, ambiguous task or policy, or impossible world. Say
   how confident you are and what single fact would change your answer.
5. If the world looks impossible, name the rule that is missing.
````

Verify step 1 yourself on the world. Models will often agree with the reference by default, so
check that the answer to step 1 came from the question and not from the gold query.

## Reviewing at scale

- Start with the top of the suite report: domain-validated counterexamples first.
- Keep a short table of your decisions per case id (candidate defect, reference defect, ambiguous,
  impossible). The share of reference defects is itself worth knowing about your eval set.
- Review a stratified sample if there are many findings: by family, by [validity tier](../concepts/validity-and-fidelity.md#validity-tiers), by case.
