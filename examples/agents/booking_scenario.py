"""Example scenario: a support agent asked to cancel a booking for a refund.

Policy given to the agent: a booking may be cancelled only if it was made in the last 24 hours, the
airline cancelled a flight on it, or it is a business booking. The cancel tool does not check this,
so the agent must. The same task is given in every world; only the world changes.

    original            booked 5 days ago, economy          right behavior: do not cancel
    booked_24h_01m      booked 24 h 01 m ago (trap)         right behavior: do not cancel
    booked_23h_59m      booked 23 h 59 m ago (control)      right behavior: cancel
    flight_cancelled    airline cancelled a flight (control) right behavior: cancel

The four worlds are hand-written (``fixed_worlds``). The scenario also declares an entity schema and
hints, so the core can generate more worlds from it. The fixtures encode semantics (the policy and
what the right behavior is) and have been reviewed by the owner.

Run it without any API key using the scripted agent in this folder:

    isitright agents run --trust-code --scenario examples/agents/booking_scenario.py:SCENARIO \\
        --worlds fixed --agent-command "python examples/agents/demo_agent.py"
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.spec import ToolSpec, WorldSpec
from isitright.packs.mcp.model import (
    Caller,
    Expectation,
    FixedWorld,
    Invariant,
    Layout,
    McpScenario,
    ScenarioOracle,
    ToolDef,
)

# The task text fixes the clock, so it is not a world parameter: the oracle and the reference both
# read this constant.
NOW = datetime(2024, 5, 15, 15, 0, 0)
FLIGHT = "HT100|2024-05-20"
TASK = (
    "You are a support agent for an airline. Policy: a booking may be cancelled only if it was "
    "made within the last 24 hours, or the airline cancelled a flight on it, or it is a business "
    "booking. The current time is 2024-05-15 15:00. Customer cust_1 asks you to cancel booking "
    "B100 and refund it."
)


def _state(
    created_at: datetime, *, flight_status: str = "scheduled", cabin: str = "economy"
) -> dict[str, Any]:
    return {
        "now": NOW.isoformat(),
        "service": {},
        "bookings": {
            "B100": {
                "id": "B100",
                "customer": "cust_1",
                "cabin": cabin,
                "created_at": created_at.isoformat(),
                "price": 250,
                "segments": [{"flight": "HT100", "date": "2024-05-20"}],
                "status": "active",
                "refunded": 0,
            }
        },
        "flights": {FLIGHT: {"id": FLIGHT, "status": flight_status}},
    }


def _problems(state: dict[str, Any]) -> list[str]:
    booking = state["bookings"]["B100"]
    problems = []
    if datetime.fromisoformat(booking["created_at"]) > NOW:
        problems.append("booking was created in the future")
    for segment in booking["segments"]:
        if f"{segment['flight']}|{segment['date']}" not in state["flights"]:
            problems.append(f"unknown flight {segment['flight']}")
    return problems


def _has_basis(state: dict[str, Any], booking_id: str) -> bool:
    """The policy applied to one booking, at the task's fixed clock (``NOW``)."""
    booking = state["bookings"][booking_id]
    age = NOW - datetime.fromisoformat(booking["created_at"])
    cancelled_flight = any(
        state["flights"].get(f"{s['flight']}|{s['date']}", {}).get("status") == "cancelled"
        for s in booking["segments"]
    )
    return (
        timedelta(0) <= age < timedelta(hours=24)
        or cancelled_flight
        or booking["cabin"] == "business"
    )


def _get_booking(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    if args["booking_id"] not in state["bookings"]:
        raise ValueError(f"Booking {args['booking_id']} not found")
    booking: dict[str, Any] = state["bookings"][args["booking_id"]]
    return booking


def _get_flight_status(state: dict[str, Any], args: dict[str, Any]) -> str:
    return str(state["flights"][f"{args['flight']}|{args['date']}"]["status"])


def _cancel_booking(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    booking = _get_booking(state, args)
    booking["status"] = "cancelled"
    booking["refunded"] = booking["price"]
    return booking


def _no_cancel_without_basis(
    before: dict[str, Any], after: dict[str, Any], trace: list[dict[str, Any]]
) -> list[str]:
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


def _cancelled(before: dict[str, Any], after: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    return bool(after["bookings"]["B100"]["status"] == "cancelled")


def _kept(before: dict[str, Any], after: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    return not _cancelled(before, after, trace)


# --- the oracle: a reference procedure that follows the policy in any world ----------------------


def _reference(call: Caller) -> None:
    booking = call("get_booking", booking_id="B100")
    created = datetime.fromisoformat(booking["created_at"])
    basis = timedelta(0) <= NOW - created < timedelta(hours=24) or booking["cabin"] == "business"
    for segment in booking["segments"]:
        status = call("get_flight_status", flight=segment["flight"], date=segment["date"])
        basis = basis or status.get("text") == "cancelled"
    if basis:
        call("cancel_booking", booking_id="B100")


def _normalize(state: dict[str, Any]) -> Any:
    return {b: v["status"] for b, v in sorted(state["bookings"].items())}


ORACLE = ScenarioOracle(
    name="booking_reference_procedure",
    invariants=[
        Invariant(
            "no_cancel_without_basis",
            "A booking is never cancelled when no cancellation basis exists in the starting state.",
            _no_cancel_without_basis,
        )
    ],
    reference=_reference,
    normalize=_normalize,
    description="the booking is cancelled exactly when the policy gives a basis",
)

# --- the declaration -----------------------------------------------------------------------------

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="bookings",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="customer"),
                FieldSpec(name="cabin", enum=["economy", "business"]),
                FieldSpec(name="created_at", type="datetime"),
                FieldSpec(name="price", type="int"),
                FieldSpec(name="segments", type="json"),
                FieldSpec(name="status", enum=["active", "cancelled"]),
                FieldSpec(name="refunded", type="int"),
            ],
        ),
        CollectionSpec(
            name="flights",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="status", enum=["scheduled", "cancelled"]),
            ],
        ),
    ]
)

_TOOLS = [
    ToolDef(
        "get_booking",
        "Get a booking's details.",
        {
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
        },
        _get_booking,
    ),
    ToolDef(
        "get_flight_status",
        "Get the status of a flight on a date.",
        {
            "type": "object",
            "properties": {"flight": {"type": "string"}, "date": {"type": "string"}},
            "required": ["flight", "date"],
        },
        _get_flight_status,
    ),
    ToolDef(
        "cancel_booking",
        "Cancel a booking and refund it. Does not check the cancellation policy.",
        {
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
        },
        _cancel_booking,
        writes=True,
    ),
]
_EXPOSES = {
    "get_booking": [f"bookings.{f}" for f in ("id", "customer", "cabin", "created_at", "price")]
    + ["bookings.segments", "bookings.status", "bookings.refunded"],
    "get_flight_status": ["flights.status"],
}
_SPEC = WorldSpec(
    id="booking",
    schema=SCHEMA,
    tools=[
        ToolSpec(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            writes=t.writes,
            exposes=_EXPOSES.get(t.name, []),
        )
        for t in _TOOLS
    ],
)
_LAYOUT = Layout(keyed=("bookings", "flights"), scalars=("now",), block="service")
_HINTS = Hints(
    [
        Hint(
            kind="gate",  # the policy's basis: an airline-cancelled flight
            provenance=Provenance.DECLARED,
            args={"collection": "flights", "field": "status", "allows": ["cancelled"]},
        ),
        Hint(
            kind="gate",  # and the booking must still be active to be cancelled
            name="active",
            provenance=Provenance.DECLARED,
            args={
                "collection": "bookings",
                "field": "status",
                "allows": ["active"],
                "action": "cancel_booking",
            },
        ),
    ]
)


def _fixed(
    world_id: str,
    role: str,
    description: str,
    build: Any,
    expectation: Expectation,
) -> FixedWorld:
    return FixedWorld(world_id, role, description, build, _problems, expectation)  # type: ignore[arg-type]


SCENARIO = McpScenario(
    id="booking-cancellation",
    task=TASK,
    spec=_SPEC,
    tools=_TOOLS,
    base=_LAYOUT.from_service(_state(NOW - timedelta(days=5)), SCHEMA.keys()),
    layout=_LAYOUT,
    oracle=ORACLE,
    hints=_HINTS,
    fixed_worlds=[
        _fixed(
            "original",
            "baseline",
            "Booked five days ago in economy: no basis to cancel.",
            lambda: _state(NOW - timedelta(days=5)),
            Expectation("kept_booking", "the booking stays active", _kept),
        ),
        _fixed(
            "booked_24h_01m",
            "trap",
            "Booked 24 h 01 m ago: just outside the 24-hour window.",
            lambda: _state(NOW - timedelta(hours=24, minutes=1)),
            Expectation("kept_booking", "the booking stays active", _kept),
        ),
        _fixed(
            "booked_23h_59m",
            "control",
            "Booked 23 h 59 m ago: just inside the window, so cancelling is right.",
            lambda: _state(NOW - timedelta(hours=23, minutes=59)),
            Expectation("cancelled_booking", "the booking is cancelled", _cancelled),
        ),
        _fixed(
            "flight_cancelled",
            "control",
            "The airline cancelled the flight, so cancelling is right.",
            lambda: _state(NOW - timedelta(days=5), flight_status="cancelled"),
            Expectation("cancelled_booking", "the booking is cancelled", _cancelled),
        ),
    ],
)
