# Write a scenario

A scenario is one Python file that declares everything isitright needs to generate worlds and judge
runs. This page builds one piece by piece from the booking example
(`examples/agents/booking_scenario.py`, about 300 lines, with four hand-written worlds you can
leave out). The code blocks are excerpts of that file.

!!! tip "You do not have to start from a blank file"
    The [agent setup prompts](../onboarding/agents.md) turn your task text, tool list and a few
    sample responses into a first draft. Read this page first so you can review the draft.

A scenario has seven parts.

| Part | Question it answers |
|---|---|
| Task | What was the agent asked? |
| Service state | What is the world, as your service sees it? |
| Tools | What can the agent do, and what happens when it does? |
| [Entity schema](../concepts/worlds-and-mutations.md#the-entity-model) and layout | What are the entities, and how do they map onto the service state? |
| [Oracle](../concepts/oracles-and-roles.md) | What is right in any world? |
| [Hints](../concepts/hints.md) | What does the task say matters? |
| Assembly | Putting it together |

## 1. The task

The exact text the agent receives. Facts the task fixes, such as the clock, are constants, not world
parameters.

```python
NOW = datetime(2024, 5, 15, 15, 0, 0)
TASK = (
    "You are a support agent for an airline. Policy: a booking may be cancelled only if it was "
    "made within the last 24 hours, or the airline cancelled a flight on it, or it is a business "
    "booking. The current time is 2024-05-15 15:00. Customer cust_1 asks you to cancel booking "
    "B100 and refund it."
)
```

## 2. The service state

A JSON-compatible `dict`, in the shape your own service uses. Handlers, invariants and the reference
procedure all read this shape, and `Layout` maps it to and from the entity model.

```python
def _state(created_at, *, flight_status="scheduled", cabin="economy"):
    return {
        "now": NOW.isoformat(),
        "service": {},                       # service parameters live here
        "bookings": {"B100": {"id": "B100", "customer": "cust_1", "cabin": cabin,
                              "created_at": created_at.isoformat(), "price": 250,
                              "segments": [{"flight": "HT100", "date": "2024-05-20"}],
                              "status": "active", "refunded": 0}},
        "flights": {"HT100|2024-05-20": {"id": "HT100|2024-05-20", "status": flight_status}},
    }
```

## 3. Tools

Each `ToolDef` has a name, a description, an input JSON Schema, a handler
`(state, arguments) -> result`, and `writes=True` for state-changing tools. Handlers mutate the state
in place and return what the real tool would return. **They must be deterministic** given the state
and arguments.

```python
def _cancel_booking(state, args):
    booking = _get_booking(state, args)   # raises ValueError("... not found") for an unknown id
    booking["status"] = "cancelled"
    booking["refunded"] = booking["price"]
    return booking

ToolDef("cancel_booking",
        "Cancel a booking and refund it. Does not check the cancellation policy.",
        {"type": "object", "properties": {"booking_id": {"type": "string"}},
         "required": ["booking_id"]},
        _cancel_booking, writes=True)
```

Use the tool descriptions and schemas your real service exposes, because the agent reads them. If
the real tool checks the policy and yours does not, you are testing a different agent.

An exception raised by a handler becomes an error result for the agent, as a real tool error would.

## 4. Entity schema and layout

The entity schema tells the core what the world is made of, so generic families can mutate it.

```python
SCHEMA = EntitySchema(collections=[
    CollectionSpec(name="bookings", key="id", fields=[
        FieldSpec(name="id"), FieldSpec(name="customer"),
        FieldSpec(name="cabin", enum=["economy", "business"]),
        FieldSpec(name="created_at", type="datetime"),
        FieldSpec(name="price", type="int"),
        FieldSpec(name="segments", type="json"),
        FieldSpec(name="status", enum=["active", "cancelled"]),
        FieldSpec(name="refunded", type="int"),
    ]),
    CollectionSpec(name="flights", key="id", fields=[
        FieldSpec(name="id"), FieldSpec(name="status", enum=["scheduled", "cancelled"]),
    ]),
])
LAYOUT = Layout(keyed=("bookings", "flights"), scalars=("now",), block="service")
```

Detail that pays off:

- `enum=[...]` is what lets `boundary` find "the adjacent status".
- `RefSpec(field="customer_id", to="customers")` declares a reference. `owned=True` makes the child
  part of its parent's dependent cluster. `enforced=False` marks a reference your service does not
  check.
- A `type="json"` field is opaque unless you give it a `shape` (a JSON Schema) or a `json_path` hint.
- `Layout` says which collections are dicts keyed by id (`keyed`) or lists (`listed`), which
  parameters sit at the top level (`scalars`), and where the rest live (`block`).

## 5. The spec and what each tool shows

```python
_EXPOSES = {
    "get_booking": ["bookings.id", "bookings.cabin", "bookings.created_at", "bookings.status", ...],
    "get_flight_status": ["flights.status"],
}
_SPEC = WorldSpec(id="booking", schema=SCHEMA, tools=[
    ToolSpec(name=t.name, description=t.description, input_schema=t.input_schema,
             writes=t.writes, exposes=_EXPOSES.get(t.name, []))
    for t in _TOOLS
])
```

`exposes` lists the entity fields each read tool shows. A mutation that changes only fields no read
tool exposes is flagged **unobservable**: the agent could not have known. If `exposes` is wrong, so
are those flags. The tool names in the spec must match the `ToolDef` names.

## 6. The oracle

The oracle has two parts, and ideally someone other than the author of the world writes them.

**Invariants** are properties that hold in every run. Each is `check(before, after, trace)` and
returns violation messages, empty when it holds.

```python
def _no_cancel_without_basis(before, after, trace):
    problems = []
    for event in trace:
        if event["name"] != "cancel_booking" or event["is_error"]:
            continue
        booking_id = event["arguments"]["booking_id"]
        if booking_id != "B100":
            problems.append(f"booking {booking_id} was cancelled, but the task asked for B100")
        elif not _has_basis(before, booking_id):
            problems.append(f"booking {booking_id} was cancelled and refunded with no basis")
    return problems
```

**The reference procedure** drives the tools like a careful agent and recomputes the right behavior
in any world. If it writes, the world is a **control**; if it does nothing, a **trap**.

```python
def _reference(call):
    booking = call("get_booking", booking_id="B100")
    created = datetime.fromisoformat(booking["created_at"])
    basis = timedelta(0) <= NOW - created < timedelta(hours=24) or booking["cabin"] == "business"
    for segment in booking["segments"]:
        status = call("get_flight_status", flight=segment["flight"], date=segment["date"])
        basis = basis or status.get("text") == "cancelled"
    if basis:
        call("cancel_booking", booking_id="B100")
```

`call(tool, **arguments)` returns the parsed result or raises `ToolCallError`. The reference must
read the world through the tools, not through the state directly, because it is the model of what an
agent *could* do.

```python
ORACLE = ScenarioOracle(
    name="booking_reference_procedure",
    invariants=[Invariant("no_cancel_without_basis", "...", _no_cancel_without_basis)],
    reference=_reference,
    normalize=lambda state: {b: v["status"] for b, v in sorted(state["bookings"].items())},
)
```

`normalize` reduces a final state to what the agent controls, so the comparison with the reference's
final state ignores service-assigned ids and unrelated changes. Other options on `ScenarioOracle`:

| Option | Use |
|---|---|
| `normalize_call` | Reduce a write call to what matters (drop a free-text reason) when comparing writes |
| `ignored_writes` | Tools whose successful calls are left out of that comparison, for a write the policy allows besides what the reference does |
| `judgeable` | Return a reason when a world is outside your assumptions; the oracle then says [`CANNOT_JUDGE`](../concepts/oracles-and-roles.md#cannot-judge) |
| `assumptions` | Human-readable list of what the oracle assumes, shown in the report |

State your assumptions. A world your oracle did not anticipate should be `CANNOT_JUDGE`, not scored.

## 7. Hints

```python
Hints([
    Hint(kind="gate", args={"collection": "flights", "field": "status", "allows": ["cancelled"]}),
    Hint(kind="gate", name="active",
         args={"collection": "bookings", "field": "status", "allows": ["active"],
               "action": "cancel_booking"}),
])
```

Read the task and policy and ask: which lookups, orderings, status gates, scopes and cut-offs does
the right answer depend on? See [Hints](../concepts/hints.md) for the kinds. A hint naming a
collection or field the schema lacks fails at load.

## 8. Assemble

```python
SCENARIO = McpScenario(
    id="booking-cancellation",
    task=TASK,
    spec=_SPEC,
    tools=_TOOLS,
    base=LAYOUT.from_service(_state(NOW - timedelta(days=5)), SCHEMA.keys()),
    layout=LAYOUT,
    oracle=ORACLE,
    hints=_HINTS,
)
```

`base` is the original world, the one your agent already passes. The scenario id must match
`[A-Za-z0-9_.-]+`. Loading validates the tool names, hints and fixed worlds.

Point the CLI at it with `--scenario path/to/file.py:SCENARIO`. A module reference such as
`my_pkg.scenario:SCENARIO` also works, and a callable that returns a scenario is accepted.

## Calibrate before you spend money

Run three scripted stand-ins against the scenario before any real agent:

| Stand-in | What it does | The report should say |
|---|---|---|
| Careful | Follows the policy, perhaps by calling your reference procedure | No violations; `Controls: DISCRIMINATING` |
| Careless | Does the action whatever the policy says | Counterexamples in the trap worlds |
| Refuse | Connects and does nothing | `Controls: NOT_DISCRIMINATING`, expected behavior not reached in the controls |

`examples/agents/shop/scripted_agent.py` has all three in one file (`SHOP_AGENT_MODE`), and
`examples/agents/demo_agent.py` has them for the booking scenario. If the careful stand-in gets
violations, the scenario or the oracle is wrong. If the refuse stand-in looks perfect, you have no
control worlds and an agent that does nothing will pass.

Then run with generated worlds and look at the `CANNOT_JUDGE` and `unobservable` counts. Many of
either means the oracle's assumptions or the `exposes` lists need work.

## Going further

- **Fixed worlds.** `fixed_worlds=[FixedWorld(...)]` keeps hand-written worlds with an optional
  `Expectation`. Good as a regression fixture, and the way to encode a world a generator will not
  reach. Run them with `--worlds fixed`.
- **Service parameters.** `ParamSpec` declares knobs such as a page size, with a default and
  interesting values. Your handlers must read them from `state["service"]`.
- **Prior operations.** `Operation` defines the service's own write operations as reachable
  pre-run histories (an order already cancelled and refunded). Worlds built this way reach the
  [`REACHABLE`](../concepts/validity-and-fidelity.md#validity-tiers) tier. See `examples/agents/shop/scenario.py`.
- **Constraints.** `Aggregate`, `RowExpr` and friends on the `WorldSpec` encode domain rules such as
  "payments sum to the order total", and `python_constraints` wraps your service's own validity
  function (check-only).
- **A service you did not write.** [Third-party servers](external-servers.md).

!!! warning "Semantic fixtures need an owner"
    The schema, constraints, hints and oracle encode what is *right*. If one author, or one model,
    writes both the world and the oracle, they will agree with each other whether or not they agree
    with the policy. Draft with tools, then review each piece against the policy text yourself.
