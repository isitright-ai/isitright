# About

## What isitright is for

Teams building text-to-SQL or tool-using agents who have an eval set and want to know which passes are
real. Researchers checking benchmark quality and the reliability of execution-based or state-based
grading. Eval-infrastructure teams who want this as a diagnostic inside an existing framework. People
who need the same audit in a domain isitright does not cover, and are willing to [write a mutator or a
host](guides/extending.md).

## What you can rely on

These are design rules the tool holds itself to. They explain behaviors that can look strict.

1. **[Report evidence precisely](concepts/evidence.md).** The [divergence](concepts/evidence.md#divergence_status),
   its [validity](concepts/validity-and-fidelity.md#validity-tiers), the
   [execution fidelity](concepts/validity-and-fidelity.md#execution-fidelity), the
   [oracle](concepts/oracles-and-roles.md) and its limits, the
   [run counts](concepts/live-agents.md) and the
   [attribution](concepts/evidence.md#attribution_status) stay separate fields.
2. **[The gold is fallible](concepts/oracles-and-roles.md).** A reference program is an
   implementation too, so a disagreement does not say which side is wrong.
3. **[Validity has tiers](concepts/validity-and-fidelity.md#validity-tiers).** Domain-validated means
   "passed the rules provided".
4. **[Not found is not correct](concepts/evidence.md#not-found-is-not-correct).** Reports state
   budgets, coverage and skipped families.
5. **[Reproducibility is mandatory](concepts/minimization-and-replay.md).** Seeds, configuration,
   hashes of inputs, the mutation path and a minimized replay artifact.
6. **No model or API dependency in the core.** LLM-based pieces, such as
   [proposed hints](concepts/hints.md#provenance), are optional and labeled.
7. **[Safe by default](#safety).** Perturbed worlds live in disposable instances, in-process engines
   or isitright-hosted fakes. Your data and systems are never modified.
8. **[Observed failures are not reliability claims](concepts/live-agents.md#observed-failure-versus-rate-claim).**
   A rate claim needs repeated runs and a test.
9. **Fixtures that encode semantics are owner-approved.** Agents may draft; people approve. See
   [Onboarding with an LLM](onboarding/index.md#the-rules-for-llm-drafted-inputs).
10. **Trusted code only.** [Scenarios](agents/write-a-scenario.md), mutators, oracles and validators
    are Python and run only with `--trust-code`.

## Safety

The tool never modifies your data or systems. SQL runs as a single read-only statement under an
authorizer, `query_only` and time and row limits. Each MCP run is a fresh server process with a
process-tree kill on timeout. Credentials are runtime-only and never written to reports. A live agent
runs with your permissions and network: isitright does not sandbox it.

## Contributing and licence

Source and issues: [github.com/isitright-ai/isitright](https://github.com/isitright-ai/isitright).
See `CONTRIBUTING.md` in the repository. Semantic fixtures (entity schemas, constraints, hint
declarations, oracle rules, expected results) need owner review. MIT licence.

## Where it sits

isitright's loop (change the input, run, compare, shrink) is property-based testing combined with
differential testing, applied to evals. Tools that apply it in one domain exist. isitright applies it
to *your* agent and *your* passing eval cases, by changing world state, and works the same way for
SQL and for tool-using agents.

| Area | Existing approach | How isitright differs |
|---|---|---|
| Text-to-SQL | SQL equivalence checkers (SpotIt, VeriEQL) and test-suite accuracy search for a database where a gold and a generated query differ | isitright reports how valid the database is under your own domain rules, runs it on the real engine, minimizes and replays it, ranks a whole suite, and exports each finding as a new eval case. The same pipeline audits agents |
| Auditing evals | EvalPlus strengthens a public benchmark with generated inputs | isitright audits your own eval set rather than shipping a stronger public one, and changes the world rather than function inputs |
| Agent robustness | Benchmarks such as AgentPerturb and ToolRobustBench perturb prompts, tool interfaces and tool outputs; the right answer stays the same | isitright changes what is *true* in the world and recomputes the right answer, so it catches an agent that fails to notice the change |
| Testing engines | Hypothesis does property-based testing for fast, deterministic functions | isitright handles slow, costly, random subjects with baselines, budgets and statistical tests, and keeps worlds valid. It uses Hypothesis to draw edge values |
