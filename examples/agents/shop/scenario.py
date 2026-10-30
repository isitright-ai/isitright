# Proposed fixture: pending owner review
"""Scenario: a retail support-desk agent that must cancel and refund the customer's latest order.

Three authors, so that fixtures and checks do not agree merely because one hand wrote both:

    shop_service.py    Claude: the simulated service, the state, the hand-written worlds W0 to W11
    oracle.py          an OpenAI model: the invariants, the right behavior per world, a reference
                       procedure (read in full and kept unchanged; see its provenance header)
    this file          Claude: the declaration that ties them to isitright's core

This file declares, for the generic families, what the shop is: its entity schema, constraints,
tools, service parameters, hints and an oracle. It does not list the worlds: the core generates
them. The 24 hand-written worlds are kept as ``fixed_worlds``, a regression fixture.

The hints are written from the task text, the tool schemas and the baseline trace (the calls the
oracle author's reference procedure makes in the unmutated world), not from any list of worlds.

Run it without any API key using the scripted agents:

    isitright agents run --trust-code --scenario examples/agents/shop/scenario.py:SCENARIO \\
        --agent-command "python examples/agents/shop/scripted_agent.py"
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import oracle
import shop_service as service

from isitright.core.constraints import Aggregate, PythonConstraint, RowExpr
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, RefSpec
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.hosts import Fidelity
from isitright.core.mutations import World
from isitright.core.spec import Operation, ParamSpec, ToolSpec, WorldSpec
from isitright.core.world import State
from isitright.packs.mcp.model import (
    Expectation,
    FixedWorld,
    Invariant,
    Layout,
    McpScenario,
    ScenarioOracle,
    ToolCallError,
)
from isitright.packs.mcp.runtime import RuntimeCaller, ServiceRuntime

NAME, ZIP = "Maria Lopez", "10027"

# --- the entity schema, from the service's state shape --------------------------------------------

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="customers",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="name"),
                FieldSpec(name="zip"),
                FieldSpec(name="email", optional=True),
            ],
            embedded=[
                CollectionSpec(
                    name="payment_methods",
                    key="id",
                    fields=[
                        FieldSpec(name="id"),
                        FieldSpec(name="type", enum=["card", "gift_card"]),
                        FieldSpec(name="label"),
                    ],
                )
            ],
        ),
        CollectionSpec(
            name="orders",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="customer_id"),
                FieldSpec(name="status", enum=list(service.STATUSES)),
                FieldSpec(name="created_at", type="datetime"),
                FieldSpec(name="total", type="float"),
                FieldSpec(name="items", type="json"),
            ],
            references=[RefSpec(field="customer_id", to="customers")],
        ),
        CollectionSpec(
            name="payments",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="order_id"),
                FieldSpec(name="method_id"),
                FieldSpec(name="amount", type="float"),
            ],
            references=[
                RefSpec(field="order_id", to="orders", owned=True),
                # The service does not check that the method still exists (world W6 is valid).
                RefSpec(field="method_id", to="customers.payment_methods", enforced=False),
            ],
        ),
        CollectionSpec(
            name="refunds",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="payment_id"),
                FieldSpec(name="order_id"),
                FieldSpec(name="method_id"),
                FieldSpec(name="amount", type="float"),
            ],
            references=[
                RefSpec(field="payment_id", to="payments", owned=True),
                RefSpec(field="order_id", to="orders", owned=True),
            ],
        ),
    ]
)
KEYS = SCHEMA.keys()
LAYOUT = Layout(
    keyed=("customers", "orders", "payments"),
    listed=("refunds",),
    scalars=("now",),
    block="service",
    defaults={"list_order": "ascending", "page_size": 10},
)

# --- tools: what each read tool shows the agent -----------------------------------------------

_TOOL_NOTES: dict[str, dict[str, Any]] = {
    # `exposes` lists entity fields a read tool's output contains (from the tool descriptions and
    # the baseline outputs). Write tools show only the agent's own action, so they expose nothing:
    # that is why a refund that already exists before the run cannot be seen by any read tool.
    "find_customer": {
        "exposes": [
            "customers.id",
            "customers.name",
            "customers.zip",
            "customers.email",
            "customers.payment_methods",
        ]
    },
    "list_orders": {
        "exposes": ["orders.id", "orders.status", "orders.created_at", "orders.total"],
        "list_field": "orders",
    },
    "get_order": {
        "exposes": [
            "orders.id",
            "orders.customer_id",
            "orders.status",
            "orders.created_at",
            "orders.total",
            "orders.items",
            "payments.id",
            "payments.order_id",
            "payments.method_id",
            "payments.amount",
        ],
        "nested_lists": ["payments"],
    },
}
TOOL_SPECS = [
    ToolSpec(
        name=t.name,
        description=t.description,
        input_schema=t.input_schema,
        writes=t.writes,
        **_TOOL_NOTES.get(t.name, {}),
    )
    for t in service.TOOLS
]

PARAMS = [
    ParamSpec(name="page_size", type="int", default=10, description="default page size"),
    ParamSpec(
        name="max_page_size",
        type="int",
        default=None,
        values=[1, 2],
        description="a server-side cap below the requested page size",
    ),
    ParamSpec(name="list_order", default="ascending", description="listing order"),
    ParamSpec(name="empty_ack", default=None, description="tools whose first reply is empty"),
    ParamSpec(name="hide_payments", default=None, description="get_order shows no payments"),
]

# --- prior operations: the service's own write tools, as reachable pre-run histories --------------


def _apply_tools(state: State, calls: list[tuple[str, dict[str, Any]]]) -> State | None:
    runtime = ServiceRuntime.for_world(_scenario_ref(), World(state))
    for tool, arguments in calls:
        try:
            runtime.call(tool, arguments)
        except ValueError:
            return None
    return LAYOUT.from_service(runtime.service, KEYS)


def _scenario_ref() -> McpScenario:
    return SCENARIO


def _orders(state: State) -> Iterator[dict[str, Any]]:
    yield from state.entities("orders")


def _payments_of(state: State, order_id: str) -> list[dict[str, Any]]:
    return [p for p in state.entities("payments") if p["order_id"] == order_id]


def _cancel_options(state: State) -> Iterator[dict[str, Any]]:
    for order in _orders(state):
        if order["status"] != "cancelled":
            yield {"order_id": order["id"]}


def _cancel(state: State, args: dict[str, Any]) -> State | None:
    return _apply_tools(
        state, [("cancel_order", {"order_id": args["order_id"], "reason": "no longer needed"})]
    )


def _cancel_and_refund(state: State, args: dict[str, Any]) -> State | None:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("cancel_order", {"order_id": args["order_id"], "reason": "no longer needed"})
    ]
    calls += [
        ("refund", {"payment_id": p["id"], "amount": p["amount"]})
        for p in _payments_of(state, args["order_id"])
    ]
    return _apply_tools(state, calls)


def _refund_options(state: State) -> Iterator[dict[str, Any]]:
    refunded = {r["payment_id"] for r in state.entities("refunds")}
    for payment in state.entities("payments"):
        if payment["id"] not in refunded:
            yield {"payment_id": payment["id"]}


def _refund_full(state: State, args: dict[str, Any]) -> State | None:
    payment = next(p for p in state.entities("payments") if p["id"] == args["payment_id"])
    return _apply_tools(
        state, [("refund", {"payment_id": payment["id"], "amount": payment["amount"]})]
    )


def _refund_part(state: State, args: dict[str, Any]) -> State | None:
    payment = next(p for p in state.entities("payments") if p["id"] == args["payment_id"])
    return _apply_tools(
        state, [("refund", {"payment_id": payment["id"], "amount": payment["amount"] / 2})]
    )


OPERATIONS = [
    Operation("cancel_order", _cancel_options, _cancel, lambda a: [("orders", a["order_id"])]),
    Operation(
        "cancel_and_refund",
        _cancel_options,
        _cancel_and_refund,
        lambda a: [("orders", a["order_id"])],
    ),
    Operation(
        "refund_in_full",
        _refund_options,
        _refund_full,
        lambda a: [("payments", a["payment_id"])],
    ),
    Operation(
        "refund_in_part",
        _refund_options,
        _refund_part,
        lambda a: [("payments", a["payment_id"])],
    ),
]

# --- the oracle: the OpenAI model's invariants and reference procedure ---------------------


def _invariant(name: str, description: str, check: Any) -> Invariant:
    return Invariant(name, description, lambda b, a, t: list(check(b, a, t)))


def _reference(call: Any) -> None:
    def reference_call(tool: str, **arguments: Any) -> dict[str, Any]:
        try:
            return call(tool, **arguments)  # type: ignore[no-any-return]
        except ToolCallError as error:
            raise oracle.ToolError(str(error)) from error

    oracle.reference_procedure(reference_call, NAME, ZIP)


def _normalize(state: dict[str, Any]) -> Any:
    """What the agent can change: which orders are cancelled and which refunds exist.

    Service-assigned refund ids are dropped, and other fields (a status that a world change moved)
    are left out, so the comparison is about the agent's actions only.
    """
    return {
        "cancelled": sorted(
            oid for oid, o in state["orders"].items() if o["status"] == "cancelled"
        ),
        "refunds": sorted(
            (r["payment_id"], r["order_id"], r["method_id"], r["amount"]) for r in state["refunds"]
        ),
    }


def _judgeable(world: World) -> str | None:
    """The oracle states that the only autonomous change during a run is an order status change."""
    for timer in world.timers:
        for edit in timer.edits:
            path = getattr(edit, "path", None)
            if getattr(edit, "collection", None) != "orders" or path != ["status"]:
                return (
                    "outside the oracle's assumptions: 'The only autonomous external state "
                    "change is a logged __world_change__ status event'"
                )
    return None


ORACLE = ScenarioOracle(
    name="shop_reference_procedure",
    invariants=[_invariant(n, d, fn) for n, (d, fn) in oracle.INVARIANTS.items()],
    reference=_reference,
    normalize=_normalize,
    normalize_call=lambda tool, args: (tool, {k: v for k, v in args.items() if k != "reason"}),
    judgeable=_judgeable,
    assumptions=oracle.ASSUMPTIONS,
    description=(
        "the final cancellations and refunds equal those of the oracle author's reference procedure"
    ),
)

# --- hints: from the task text, the tool schemas and the baseline trace ---------------------------

TASK_HINTS = [
    Hint(
        kind="lookup",
        provenance=Provenance.DECLARED,
        args={"collection": "customers", "fields": ["name", "zip"], "value": [NAME, ZIP]},
    ),
    Hint(
        kind="ordering",  # "my most recent order"
        provenance=Provenance.DECLARED,
        args={"collection": "orders", "field": "created_at", "direction": "desc"},
    ),
    Hint(
        kind="gate",  # policy 2: "You may cancel an order only if its status is `pending`"
        provenance=Provenance.DECLARED,
        args={
            "collection": "orders",
            "field": "status",
            "allows": ["pending"],
            "action": "cancel_order",
        },
    ),
    Hint(
        kind="scope",  # policy 4: "Act only on the customer you identified"
        provenance=Provenance.DECLARED,
        args={"collection": "orders", "where": "customer_id in $lookup.id"},
    ),
    Hint(
        kind="threshold",  # list_orders: `page_size` defaults to 10 in the tool schema
        name="page_size",
        provenance=Provenance.HARVESTED_SCHEMA,
        args={"collection": "orders", "count": 10, "where": "customer_id in $lookup.id"},
    ),
]


def _base_state() -> State:
    return LAYOUT.from_service(service.baseline(), KEYS)


def _baseline_trace_hint(scenario: McpScenario) -> Hint:
    """The calls a careful agent makes in the unmutated world, as a harvested:trace hint."""
    caller = RuntimeCaller(ServiceRuntime.for_world(scenario, World(scenario.base)))
    scenario.oracle.reference(caller)
    calls = [
        {"tool": e["name"], "arguments": e["arguments"]}
        for e in caller.trace
        if e["name"] != "__world_change__"
    ]
    return Hint(kind="trace", provenance=Provenance.HARVESTED_TRACE, args={"calls": calls})


# --- the hand-written worlds, kept as a regression fixture ---------------------------------------

WORLD_NAMES = {
    "W0": "baseline",
    "W1": "duplicate_customer",
    "W2": "pagination_boundary",
    "W3": "unordered_listing",
    "W4": "latest_shipped",
    "W5": "latest_processing",
    "W6": "method_deleted",
    "W7": "no_orders",
    "W8": "already_refunded",
    "W9": "tie_for_latest",
    "W10": "split_payment",
    "W11": "status_changes_mid_run",
    "B03": "page_cap_2",
    "B05": "utc_offsets",
    "B06": "ships_after_listing",
    "B08": "empty_refund_ack",
    "B09": "empty_cancel_ack",
    "B10": "latest_done_older_pending",
    "B11": "payments_hidden",
    "B15": "no_customer",
    "B18": "items_differ_from_paid",
    "B20": "same_name_other_zip",
    "B21": "other_customers_newer_order",
    "B22": "older_order_refunded",
}
# The author's labels. `control` marks the worlds where the right behavior is to act; a test
# checks this table against what the oracle's own expectation functions demand.
ROLES = {
    "W0": "baseline",
    "W2": "control",
    "W3": "control",
    "W10": "control",
    "B03": "control",
    "B05": "control",
    "B08": "control",
    "B09": "control",
    "B18": "control",
    "B20": "control",
    "B21": "control",
    "B22": "control",
}


def fixed_world_id(class_id: str) -> str:
    return f"{class_id}_{WORLD_NAMES[class_id]}"


def _expectation(class_id: str) -> Expectation:
    """The oracle's own expectation for W worlds; for blind B worlds, its act or no-change one."""
    if class_id in service.BLIND_RIGHT:
        action, text = service.BLIND_RIGHT[class_id]
        check = oracle.EXPECTATIONS["W0" if action == "act" else "W1"]
    else:
        check, text = oracle.EXPECTATIONS[class_id], oracle.RIGHT_BEHAVIOR[class_id]
    return Expectation(
        f"right_behavior_{class_id.lower()}", text, lambda b, a, t: bool(check(b, a, t))
    )


def _fixed(class_id: str) -> FixedWorld:
    interferences = {"W11": [service.W11_INTERFERENCE], "B06": [service.B06_INTERFERENCE]}.get(
        class_id, []
    )
    return FixedWorld(
        fixed_world_id(class_id),
        ROLES.get(class_id, "trap"),  # type: ignore[arg-type]
        service.WORLD_DESCRIPTIONS[class_id],
        service.WORLD_BUILDERS[class_id],
        service.validate,
        _expectation(class_id),
        interferences,
    )


def _shop_validity(state: State) -> list[str]:
    return list(service.validate(LAYOUT.to_service(state)))


_SPEC = WorldSpec(
    id="shop",
    schema=SCHEMA,
    constraints=[
        Aggregate(
            name="payments_sum_to_order_total",
            parent="orders",
            child="payments",
            via="order_id",
            child_field="amount",
            parent_field="total",
        ),
        RowExpr(name="created_not_after_now", collection="orders", expr="created_at <= @now"),
    ],
    python_constraints=[
        PythonConstraint(
            "shop_service.validate", _shop_validity, "the service author's own validity rules"
        )
    ],
    params=PARAMS,
    tools=TOOL_SPECS,
    operations=OPERATIONS,
    policy=service.TASK,
)

SCENARIO = McpScenario(
    id="shop-support-desk",
    task=service.TASK,
    spec=_SPEC,
    tools=service.TOOLS,
    base=_base_state(),
    layout=LAYOUT,
    oracle=ORACLE,
    hints=Hints(TASK_HINTS),
    fixed_worlds=[_fixed(class_id) for class_id in WORLD_NAMES],
    fidelity=Fidelity.SIMULATED,
)
# The trace hint needs the scenario (it runs the reference on the baseline), so it joins afterwards.
SCENARIO.hints = SCENARIO.hints.merged([_baseline_trace_hint(SCENARIO)])
_ = copy  # keep the import used when examples are edited
