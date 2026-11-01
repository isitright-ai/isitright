# Worlds and mutations

isitright works by changing the world your agent runs in. This page says what a "world" is and what a
"change" is, because everything else is built on them.

## World, state, atoms

A **world** is everything your subject can observe. For SQL that is the database. For a tool-using
agent it is the state behind its tools (customers, orders, bookings), plus service settings such as a
page size and the clock.

A **state** is one concrete version of a world: this customer, these three orders. A state is plain
data, so it can be saved in a report, compared, and rebuilt. That is why [replay](minimization-and-replay.md)
works from the concrete world and not from a random seed. Your original, passing world is the **base
state**; every changed world is the base state plus a list of changes.

**Atoms** are the smallest pieces of a state that can be changed or removed independently: a row, a
record. Two things use them: the **world diff** in a report ("one customer added") lists the atoms
that differ from the base state, and [minimization](minimization-and-replay.md) removes atoms to find
the smallest world that still fails.

## The entity model

To change a world *sensibly*, isitright needs to know its shape. Most agent worlds are records with
keys and references, so isitright describes them with one model, whatever the source: SQL tables, the
records behind an MCP service, and so on.

- **Collections** of entities, each with typed **fields** (including nullable fields and enums), a
  **key**, and **references** to other collections. A `status` field with values `pending`,
  `shipped`, `cancelled` is how isitright knows that `shipped` is the value next to `pending`.
- **Dependent clusters**: an entity together with the entities that only exist because of it, such as
  an order with its payments and line items. When isitright duplicates, deletes or moves an order,
  it moves the whole cluster, so rules like "payments sum to the order total" are not broken by
  accident.
- **Lookup keys**: the fields your task uses to find an entity, such as a customer's name and ZIP.
  You tell isitright about them with [hints](hints.md), and it uses them to build worlds such as "two
  customers share this name and ZIP".

The SQL pack builds this model automatically from your DDL: tables become collections, columns
become fields, foreign keys become references. For an agent you declare it once in the [scenario](../agents/write-a-scenario.md)
(see [Write a scenario](../agents/write-a-scenario.md#4-entity-schema-and-layout)).

## Mutations

A **mutation** is one small, described change from one world to another: "add a second customer
with the same name and ZIP", "set `amount_collected` to NULL on a copy of row 3". Each mutation
records which family produced it, a human-readable description, and the atoms it touched. Because a
mutation is data rather than code that ran, isitright can combine mutations, shrink them, and explain
them in a report.

A mutation changes one of three things, and the target decides how the [oracle](oracles-and-roles.md) judges the result:

| Target | What changes | How the oracle sees it | Example |
|---|---|---|---|
| `state` | What is true | It recomputes the right answer from the new state | Two customers named Maria Lopez in ZIP 10027 |
| `response` | What one tool call returns to the agent; the state underneath is unchanged | The mutation declares what is true underneath ("the cancel succeeded; the acknowledgement is empty") | `cancel_order` returns `{}`; a list comes back reordered |
| `timing` | The state, after a matching tool call | Like a state change, with a trigger | The order ships right after the agent reads it |

Behavior that must stay consistent across calls (a page-size cap, the sort order across pages)
cannot be faked inside one response. It is a **service parameter** that your handlers honor, and
mutators set its value. Whether a real service would ever behave that way is a plausibility question,
which your validity rules answer.

## Families

Families are generic over the entity model. Each one declares the [hint](hints.md) kinds it uses.

| Family | What it does | SQL example | Agent example |
|---|---|---|---|
| `boundary` | A harvested literal, its neighbors, the adjacent enum value | `>` versus `>=` at a literal | Status one step from `pending` |
| `missing` | Remove a field or set it to null | NULL in a nullable column | Optional field absent versus `null` |
| `duplicate` | Copy an entity with its dependent cluster | Duplicate projected rows | A second identical order |
| `key_collision` | Another entity matches a lookup key fully, partially, or misses by one step | Duplicate join key | Two customers with the task's name and ZIP |
| `dangling` | A reference to a missing entity | FK-permitted unmatched row | Payment method deleted |
| `empty` | Remove all children in a relation | Empty group | Customer with no orders |
| `tie` | Equal values on an ordering field | Ties at `ORDER BY ... LIMIT` | Two orders with the same timestamp |
| `cardinality_boundary` | Collection size at a harvested count, and one more | Group size at a `HAVING` threshold | Exactly page size plus one orders |
| `prior_operation` | Apply one of the service's own write operations before the run | n/a | Order already cancelled and refunded |
| `split` | Replace one child with two that preserve an aggregate | One row into two with the same total | Payment split across two methods |
| `representation` | Same meaning, different encoding | Trailing spaces | Timestamps with UTC offsets |
| `out_of_scope_extreme` | An entity outside the task's scope becomes extreme; the answer should not change | Unrelated row with the global maximum | Another customer's order is the shop's newest |
| `reference_swap` | An entity in scope is attached to a different existing parent (an ownership change) | A child row moved to another parent | An order changes owner |
| `temporal` | Clock, time zone and calendar edges | Date boundaries | "Same day" in two time zones |
| `units_scale` | Scale and units | Numeric scale | Cents versus dollars |
| `service_parameter` | Set a service parameter | n/a | Page-size cap of 2 |
| `response_edit` | Reorder, drop a field, empty acknowledgement, error | n/a | `refund` returns `{}` |
| `timing` | A state change after a matching tool call | n/a | The order ships after the agent lists it |
| `json_edit` | Edit inside a JSON field where a scope is declared | n/a | An item price in `orders.items[*].price` |
| `edge_value` | Zero, negative, huge, empty, padded or non-ASCII values, drawn with Hypothesis | The same | The same |

Family names are the identifiers you see in reports. The exact set depends on what your schema and [hints](hints.md) make applicable; the report's `search` section
lists the families run and skipped.

## Composition

Some disagreements need two coordinated changes: a fresh group *and* a NULL input on it, or a status
change *and* a newer order. The search composes mutations to **depth two**, regenerating proposals
from the intermediate state so the second mutation can act on what the first created.

## Your own mutators

Three levels, each getting search, validity checks, [minimization](minimization-and-replay.md), [replay](../guides/replay-and-export.md) and reporting:

1. Parameterize a built-in family (custom boundary values, target fields).
2. Compose families into a named mutator.
3. Implement the `Mutator` protocol directly.

See [Write a mutator or host](../guides/extending.md). The extension API is experimental.
