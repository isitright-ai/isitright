# Onboarding with an LLM

An audit has a few inputs that nobody has written down yet: [domain rules](../sql/domain-constraints.md), [hints](../concepts/hints.md), the [oracle](../concepts/oracles-and-roles.md), a
[scenario](../agents/write-a-scenario.md) around a service. They are the slow part of a first run. An LLM can draft most of them in
minutes from material you already have, and you review the draft.

This section gives you prompt templates for that, and says where the drafts need your judgment.
Nothing here is required. isitright itself never calls a model.

## What is manual, and what can be drafted

=== "SQL"

    | Manual step | Automate with | You still decide |
    |---|---|---|
    | Turn passing eval cases into a suite file | A script, no LLM ([Audit a suite](../sql/audit-a-suite.md)) | Which cases are in scope |
    | Get the schema as DDL | `pg_dump --schema-only`, or a prompt that fits it to the [supported subset](../sql/supported-sql.md) | Whether the trimmed schema still represents your world |
    | Write domain constraints | A profile script plus a prompt that drafts rules and questions | **Every rule.** A drafted rule is enforced as a real constraint |
    | Choose comparison policy | Read the questions, set `--ordering` | Whether order matters |
    | Review findings | A triage prompt | Which side is wrong |
    | Hints | Nothing to do: harvested from your queries | |

=== "Agents"

    | Manual step | Automate with | You still decide |
    |---|---|---|
    | Model the service: entities, tools, handlers | A prompt that drafts a scenario from your tool list and sample responses | Every handler matches the real service |
    | Declare hints | A prompt that drafts them from the task and policy; `--hints` or `agents hints propose` | Which to confirm |
    | Write the oracle: invariants and a reference procedure | A prompt, in a **separate session** from the world | Whether it matches the policy |
    | Wrap your agent in a command | A prompt for your framework | |
    | Build calibration stand-ins | A prompt for careful, careless and refuse agents | |
    | Review findings | A triage prompt | Which side is wrong |

## The rules for LLM-drafted inputs

These come from how audits fail. Follow them and a draft is a head start, not a trap.

1. **The LLM drafts, you approve.** A scenario, a rule set and an oracle encode what is *right*. If
   the same model writes the world and the oracle, they will agree with each other whether or not
   they agree with your policy. Review every semantic piece against the policy text itself.
2. **Separate the author of the world from the author of the oracle.** Use two sessions. Give the
   oracle session the task and policy text and the tool list, and *not* the handlers or the
   world. Where the oracle is written without seeing the implementation, agreement means more.
3. **Mark drafts.** Start each drafted file with a comment such as
   `# Proposed fixture: pending owner review`, and remove it only when you have reviewed it.
4. **Proposed is not declared.** Hints from `agents hints` carry a `proposed` status. They prioritize
   the search and never grant a [validity tier](../concepts/validity-and-fidelity.md#validity-tiers). SQL constraints have **no** such status: a rule
   in your constraints file is enforced, and `DOMAIN_VALIDATED` then means "your rules held". A
   drafted rule that is wrong either hides real counterexamples or invents false ones.
5. **Run it.** A draft that does not load, or that a scripted careful agent fails, is wrong. See
   [calibrate](../agents/write-a-scenario.md#calibrate-before-you-spend-money).
6. **Keep secrets and data out of prompts.** Paste schemas, tool definitions, task text and
   *synthetic or anonymized* sample responses. Do not paste credentials, personal data or production
   rows. The profile script has a mode that omits values for this reason.

## Give the LLM context first

Prompts work better when the model knows what isitright is. Either point it at
[`llms.txt`](https://docs.isitright.ai/llms.txt) or paste this primer at the top of the session:

```text
You are helping me set up isitright 0.5.1, a tool that audits agent evals. It takes a passing eval
case and searches for valid changes to the world (a database, a service's state) under which the
pass no longer holds. It needs:
- a world spec: an entity schema (collections with typed fields, keys, references), constraints
  (which states are valid), and for services the tool list;
- hints: facts from the task text that tell the search which entities and fields matter. Kinds:
  lookup {collection, fields, value}, ordering {collection, field, direction asc|desc},
  gate {collection, field, allows, action}, scope {collection, where}, threshold {path, value} or
  {collection, count}, json_path {path, same_as};
- an oracle: invariants and a reference procedure that recompute what is right in a changed world.
A disagreement between agent and oracle is evidence, not a verdict on who is wrong. Drafts you write
will be reviewed by me. Where something is ambiguous, say so and ask, or list it as an assumption.
Never invent collections, fields or tools that I did not give you.
```

## Where to go

- [SQL setup](sql.md): profile script, constraints prompt, DDL fitting prompt.
- [Agent setup](agents.md): scenario, hints, oracle, agent wrapper and calibration prompts.
- [Reviewing findings](triage.md): a prompt and a checklist for deciding which side is wrong.
