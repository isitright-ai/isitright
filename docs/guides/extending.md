# Write a mutator or host

!!! warning "Experimental"
    The extension API (`isitright.core.*`) is public and marked experimental until a pack is written
    by someone other than its author. Expect changes before 1.0. If you build on it, pin the
    version and read the [changelog](https://github.com/isitright-ai/isitright/blob/main/CHANGELOG.md)
    before upgrading.

You can extend isitright without writing a pack. A custom mutator, constraint, [hint](../concepts/hints.md) kind, [oracle](../concepts/oracles-and-roles.md) or
host gets search, validity checks, [minimization](../concepts/minimization-and-replay.md), replay and reporting from the core.

| You want | Extend | Reuse |
|---|---|---|
| A new kind of perturbation | A `Mutator` | [Entity model](../concepts/worlds-and-mutations.md#the-entity-model), families, search, validity, reports |
| A world the generic families cannot express | A `Mutator`, over entities or an opaque state | Everything else |
| A new execution environment (a statistics package, a spreadsheet engine) | A `Host` | Entity model, families, search, minimization, comparison, reports |
| A new domain rule | A constraint | Search steers by it and rejects by it |
| A new kind of task knowledge | A hint kind | Prioritization and provenance |

## A mutator

A mutator proposes mutations given the spec, the current world and the hints. A mutation is data:
it holds edits, so it can be composed, minimized and explained.

```python
from isitright.core.mutations import Mutation, SetField, World


class HalvePrice:
    family = "halve_price"      # the name reports use
    target = "state"            # "state", "response" or "timing"
    consumes = frozenset()      # the hint kinds this family reads

    def propose(self, spec, world, hints):
        for booking in world.state.entities("bookings"):
            yield Mutation(
                family=self.family,
                description=f"bookings[{booking['id']!r}].price halved",
                edits=[
                    SetField(collection="bookings", key=booking["id"], path=["price"],
                             value=booking["price"] // 2)
                ],
                touches=["bookings.price"],
            )
```

The core calls `propose` on the base world, and again on every composed parent, so the second
mutation of a depth-two path can act on what the first created. A family that raises is skipped and
noted in the report. A mutation that breaks a rule is rejected by validity checking, not by you.

To run it on a [scenario](../agents/write-a-scenario.md)'s spec directly, hand it to `search` with an `evaluate` function that runs
your subject and oracle and returns a verdict:

```python
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.stochastic import Budget

def evaluate(candidate, validity):
    state = candidate.world.state
    ...  # run your subject and the oracle on this world, then compare
    return Evaluation(Verdict.DISAGREE, validity)   # or AGREE, INCONCLUSIVE, ERROR, REJECTED

result = search(spec, World(base_state), hints, [HalvePrice()], evaluate,
                budget=Budget(attempts=50))
print(result.attempts, result.executed, result.findings)
```

`Verdict.INCONCLUSIVE` (the comparison could not decide) is never a counterexample. `search` also takes
`seed`, `depth` (default 2), `stop_on_first`, and a `progress` callback. The built-in families live in
`isitright.core.families` and are the best reference for hint-driven proposals.

Three levels of extension, in order of effort:

1. **Parameterize** a built-in family: custom boundary values, target fields, cluster definitions.
2. **Compose** families into a named mutator ("duplicate customer with a newer pending order").
3. **Implement** the `Mutator` protocol, as above.

## A host

A host makes a world available to a subject and declares how faithful it is:

```python
from contextlib import contextmanager
from isitright.core.hosts import Fidelity

class SpssHost:
    fidelity = Fidelity.NATIVE_ISOLATED

    @contextmanager
    def prepare(self, spec, world):
        path = write_sav_file(world.state)      # your code: entity state -> the tool's input
        try:
            yield path                          # the handle the subject receives
        finally:
            cleanup(path)
```

A subject (anything with `run(handle, task)`) and an oracle (`judge(task, before, run)`) plug in the
same way. Two working examples are in the repository: the SQL pack's `SqliteHost.run_pair`, and the
MCP pack's `ServiceRuntime`. Write the host so a world never touches your real data or systems:
a disposable instance, an in-process engine, or inline text.

## Hint kinds and constraints

```python
from isitright.core.hints import HintKind, register_hint_kind

register_hint_kind(HintKind("freshness", check=my_check))   # check(schema, hint) raises ModelError
```

A family reads the kinds it lists in `consumes`. A constraint that declares a value domain steers
generation; a plain Python predicate is **check-only** and listed under `unused_rules` in the
report, so generation cannot use it.

## Trust

Mutators, oracles, validators and hosts are Python. They run only with explicit trust
(`--trust-code`), and configuration files never load code.
