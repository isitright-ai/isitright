# Oracles and roles

An **oracle** decides what is right in a changed world. It returns **met**, **not met** or
**cannot judge**. It is the part of an audit most likely to be wrong, so isitright reports its kind
and its limits with every result.

## Kinds of oracle

| Kind | How the expected outcome is obtained | Where it is used |
|---|---|---|
| `REFERENCE_PROGRAM` | Run a reference program or procedure on the changed world | SQL: the reference query. Agents: the [scenario](../agents/write-a-scenario.md)'s reference procedure |
| `INVARIANT` | A property that must hold in every run | Agents: "no refund exceeds the amount paid", "writes touch only the task's customer" |
| `RELATIONAL`, `CONSTRUCTIVE`, `JUDGE` | A metamorphic relation; a world built so the answer is known; an LLM | Reserved values in the report schema. No pack ships them yet |

A scenario's oracle usually combines two: invariants that must hold everywhere, and a reference
procedure that drives the tools the way a careful agent would. The agent's run meets the oracle when
its writes equal the reference's writes in that world, so "exactly once" is part of the right
behavior.

!!! warning "The reference can be wrong"
    A gold query is an implementation. Gold errors are common in public benchmarks. A disagreement
    between [subject](subjects.md) and oracle is evidence about *both*, which is why [attribution](evidence.md#attribution_status) stays
    `UNDETERMINED`. Where you can, have the oracle written by someone other than the author of the
    world and the service. If one author writes both, they agree with each other whether or not they
    agree with your policy.

## Roles: controls and traps

For each world the reference procedure decides a **role**:

- **Control**: the reference acts. The right behavior is to do the thing.
- **Trap**: the reference does nothing. The right behavior is to leave things alone.

Controls are required. An agent that refuses everything has zero violations in every trap. Only a
control world, where acting is right, can tell a careful agent from a useless one. The report says:

- `DISCRIMINATING`: the agent reached the expected behavior in each control world at least once;
- `NOT_DISCRIMINATING`: it did not, or no control was reached. Read "no violations" in that run as
  uninformative;
- `NOT_APPLICABLE`: no control world completed a run.

You can see this in the [agent quick start](../get-started/agents.md): the careful, careless and
refuse-everything stand-ins land in three different places.

## Cannot judge

Generated worlds will reach cases the oracle's author did not anticipate: an order changing owner
mid-run, a timestamp exactly on a cut-off nobody declared. The scenario states its assumptions
(`ScenarioOracle.judgeable` returns a reason when a world falls outside them), and the oracle
answers `CANNOT_JUDGE`. These worlds are counted and reported. They are never scored as a pass or a
failure.

A frequent source: a world exactly on a numeric cut-off. A `threshold` [hint](hints.md) can declare which side
the cut-off value falls on (`holds` and `inclusive`); without that, the world is `CANNOT_JUDGE`,
because `<` versus `<=` in the reference would otherwise decide the answer. See
[Hints](hints.md).

## Comparators

A **comparator** states what "the same output" means.

- **SQL:** results compare as multisets unless the reference query has a top-level `ORDER BY`.
  Columns match `positional` (default), `by_name` or `names_and_positions`. Floats compare `exact`
  or with `isclose` (relative 1e-9, absolute 1e-12). The effective policy is recorded in every
  report. Ambiguity (collations, nondeterminism, ties under `LIMIT`) yields `INCONCLUSIVE` or
  `UNSUPPORTED`.
- **Agents:** the final state is normalized by your scenario (drop service-assigned ids and
  free-text reasons) and compared with the reference's. Calls are compared after `normalize_call`.
