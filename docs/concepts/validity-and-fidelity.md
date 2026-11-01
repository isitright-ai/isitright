# Validity and fidelity

A counterexample is only useful if the changed world could exist, and only trustworthy if you know
where the outputs were computed. isitright reports both, separately.

## Constraints: saying what is allowed

A **constraint** is a rule about which states are valid: `income >= 0`, "every order belongs to an
existing customer", "payments sum to the order total". Some come free: keys, types, references and
the database's own `CHECK` constraints. The ones that matter most you write yourself, because only you
know what your system guarantees.

Constraints do two jobs:

1. **Check.** A candidate world that breaks a rule is rejected before it runs, and counted in the
   report under `search.rejected`. Every [minimization](minimization-and-replay.md) step re-checks, so a shrunken world is still
   valid.
2. **Guide generation.** A rule is data that generators can read, not just a yes/no test. A range
   rule tells the value generator which edges to try, and an aggregate rule such as "payments sum to
   the order total" lets the `split` family build two payments that add up, instead of generating
   random ones and rejecting nearly all of them.

The constraint kinds are `Range`, `OneOf`, `NotNull`, `Unique`, `FunctionalDependency`, `Aggregate`,
`RowExpr` (a row-level expression), `JsonSum` and `Pattern`. How you write them depends on the pack:

| Pack | How you write constraints |
|---|---|
| SQL | A JSON Schema file (`--constraints`), plus `CHECK` constraints in your DDL. See [Domain constraints](../sql/domain-constraints.md) |
| Agents | Python objects such as `Aggregate(...)` and `RowExpr(...)` on the [scenario](../agents/write-a-scenario.md)'s `WorldSpec` |

A rule written as a plain Python predicate works as a check but cannot guide generation. The report
lists such rules as check-only ("rules generation could not use"), because a tight check-only rule
makes the search reject most of what it generates.

## Validity tiers

Not every valid state is equally believable, so a state gets a label for the strongest set of rules
it passed. A candidate passes the tiers that apply to it, and the report lists the tiers reached.

| Tier | Meaning | Example |
|---|---|---|
| `STRUCTURAL` | Keys, types, references and engine constraints hold | A foreign key points to an existing row |
| `DOMAIN_VALIDATED` | Every domain rule you provided holds | `income >= 0`; payments sum to the order total |
| `REACHABLE` | The state can arise through the service's own operations | Built by the `prior_operation` family |
| `TASK_CONSISTENT` | The task's story still makes sense in this world | The customer named in the task exists, unless the [mutation](worlds-and-mutations.md#mutations) tests exactly that |
| `OBSERVABLE` | The agent can see the change through some read tool | A refund that no tool exposes is unobservable |
| `SIMULATOR_CONSISTENT` | A simulated user's knowledge matches the world | Reserved; there is no simulated user yet |

Other values are `INVALID` (rejected before execution), `INDETERMINATE` and `NOT_ASSESSED`.

`DOMAIN_VALIDATED` means "passed the rules you provided", not "plausible in the real world". The
quality of this tier is the quality of your rules. With no [domain rules](../sql/domain-constraints.md) a SQL counterexample is
`STRUCTURAL` only, and the report says so. See [Domain constraints](../sql/domain-constraints.md).

!!! note "Unobservable changes"
    Tool declarations list which entity fields each read tool shows. A mutation that changes only
    fields no read tool exposes is flagged `unobservable`. That is a finding about the tool
    contract, not about the agent: nothing the agent could have done would reveal the change.

## Execution fidelity

A **host** is what makes a changed world available to your [subject](subjects.md) and runs it: a disposable SQLite
or PostgreSQL instance, an MCP server process serving the world's state, a simulation. Every host
declares how faithfully it reproduces the real system, and every result records it, so you know how
much to trust an output.

| Fidelity | Meaning | Used by |
|---|---|---|
| `NATIVE_ISOLATED` | The target engine or your real service code, on a disposable instance | SQLite; PostgreSQL; external MCP servers |
| `EMULATED` | A different engine runs translated programs | PostgreSQL SQL on DuckDB |
| `SIMULATED` | Hand-written handlers stand in for a service | The default for MCP scenarios |
| `NATIVE_INLINE`, `GENERATED`, `REPLAY_ONLY` | Reserved for later packs and hosts | |

When an emulated finding is re-executed on native PostgreSQL, the result records `found_on:
EMULATED` and `verified_on: NATIVE_ISOLATED`. A divergence that does not reproduce natively is an
**emulation artifact**, excluded from the counterexamples and never failing CI. See
[Engines](../sql/engines.md).

For a `SIMULATED` agent run, a finding is evidence about *your stand-in* for the service. If your
handlers differ from the real service, so may the finding.
