# Hints

Generic mutators applied blindly would mutate every field of every entity. **Hints** focus them.
A hint says what the task, the schemas, the program or the [baseline](live-agents.md#baseline-first) trace make important: which
entity the task looks up, which field means "most recent", which status gates an action.

Much of what makes a world interesting is written only in the task text: that "most recent" means
newest `created_at`, that only a `pending` order may be cancelled, that the customer is found by name
and ZIP. A generator cannot guess that from a schema. Hints are how you tell it.

## Hint kinds

| Kind | Arguments | Drives | Example source |
|---|---|---|---|
| `lookup` | `collection`, `fields`, `value` | Key collision, near misses | "I'm Maria Lopez, ZIP 10027" |
| `ordering` | `collection`, `field`, `direction` (`asc` or `desc`) | Ties, boundaries and out-of-scope extremes on the ordering field | "my most recent order" |
| `gate` | `collection`, `field`, `allows`, optional `action` | Adjacent enum values | "only a `pending` order may be cancelled" |
| `scope` | `collection`, optional `where` | Which entities the right answer depends on | "act only on the customer you identified" |
| `threshold` | `path` and `value`, or `collection` and `count` (optional `where`); on a field also `inclusive` and `holds` | Boundaries, cardinality boundaries, service parameters | "within 24 hours"; `list_orders` page size 10 |
| `json_path` | `path` such as `orders.items[*].price`, optional `same_as` | Edits inside a JSON field | A per-item price a careless agent could refund instead of the total |
| `trace` | `calls` | Reserved for the baseline trace, harvested automatically | The calls a reference procedure makes |

Paths are dotted (`collection.field`, `collection.embedded.field`). `$name` refers to another hint
(`$lookup.id` is the id of the entities a `lookup` hint matches), `@name` to a state parameter such
as `@now`, and `where` clauses use the same expression language as constraints. A hint that names a
collection or field the [entity model](worlds-and-mutations.md#the-entity-model) lacks is an error at load time, not a silent skip.

## Provenance

Every hint records where it came from, and the report's `search.hint_use` lists each hint with the
worlds it led to.

| Provenance | Source |
|---|---|
| `declared` | You wrote it, or confirmed it |
| `harvested:program` | Literals and columns read from the SQL with SQLGlot |
| `harvested:schema` | Defaults, enums and limits in tool schemas |
| `harvested:trace` | The baseline trace |
| `proposed` | A model suggested it and you have not confirmed it |

A `proposed` hint prioritizes the search and **never grants a [validity tier](validity-and-fidelity.md#validity-tiers)**. A proposed lookup is
not a declared one, so it cannot make a world `TASK_CONSISTENT`.

## Hints prioritize; they do not restrict

Unhinted [mutations](worlds-and-mutations.md#mutations) still run on the budget that remains. A hint author who missed something does not
blind the search. The report splits the budget into `hinted` and `unhinted` groups so you can see
how much each produced.

## Where hints come from

**SQL.** Nothing to write. The pack harvests referenced tables, columns and literals from your
queries. A literal is paired only with the columns the query compares it with, so a format string
such as the first argument of `STRFTIME` is not tried as a date.

**Agents.** Declare them in the [scenario](../agents/write-a-scenario.md) (`Hints([...])`), or write them with an LLM's help and load
them with `--hints`. [Agent setup](../onboarding/agents.md) has the prompt. Example from the shop:

```python
Hint(kind="lookup", args={"collection": "customers", "fields": ["name", "zip"],
                          "value": ["Maria Lopez", "10027"]}),
Hint(kind="ordering", args={"collection": "orders", "field": "created_at", "direction": "desc"}),
Hint(kind="gate", args={"collection": "orders", "field": "status",
                        "allows": ["pending"], "action": "cancel_order"}),
Hint(kind="scope", args={"collection": "orders", "where": "customer_id in $lookup.id"}),
```

A hints file, as `agents hints propose` writes it and `agents run --hints` reads it:

```yaml
format: isitright-hints
version: 1
hints:
  - name: gate_pending
    kind: gate
    status: proposed        # confirmed -> loaded as declared; proposed -> proposed; rejected -> dropped
    args: {collection: orders, field: status, allows: [pending], action: cancel_order}
    note: the policy allows cancelling a pending order only
```

You can register your own hint kinds with `isitright.core.hints.register_hint_kind`; a family reads
the kinds it declares in `consumes`.
