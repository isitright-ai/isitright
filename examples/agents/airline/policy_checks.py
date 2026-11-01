"""Checks for the writes the airline policy allows besides a cancellation.

The oracle in `scenario.py` compares which reservations end up cancelled. The policy also lets an
agent send a compensation certificate and change a reservation's flights, each under conditions.
Those two tools are left out of the comparison with the reference (`ignored_writes`), so a correct
extra write is not a failure; these checks make a wrong one a failure instead. They read the
service state before the run and the trace, and need no tau2 import.

Checked, from the policy's "Refunds and compensation" and "Modify flight" sections:

- a certificate goes to a silver or gold member, or a user with travel insurance or a business
  reservation, and its amount is 100 times the passengers of a reservation with a cancelled flight
  or 50 times the passengers of one with a delayed flight;
- flights are not changed on a basic economy reservation, and the trip keeps its origin,
  destination and type.

Not checked: that the agent confirmed the facts or obtained the user's consent first, that a
delay certificate came after the change or cancellation, and which reservation the user was
complaining about (any of the user's reservations can justify an amount).
"""

from __future__ import annotations

from typing import Any

State = dict[str, Any]
Trace = list[dict[str, Any]]

CANCELLED_PER_PASSENGER = 100
DELAYED_PER_PASSENGER = 50


def _successful(trace: Trace, tool: str) -> list[dict[str, Any]]:
    return [e for e in trace if e["name"] == tool and not e["is_error"]]


def _statuses(state: State, reservation: dict[str, Any]) -> set[str]:
    return {
        state["flights"][leg["flight_number"]]["dates"][leg["date"]]["status"]
        for leg in reservation["flights"]
    }


def certificate_problems(before: State, after: State, trace: Trace) -> list[str]:
    problems = []
    for event in _successful(trace, "send_certificate"):
        user_id = event["arguments"].get("user_id")
        amount = event["arguments"].get("amount")
        user = before["users"].get(user_id)
        if user is None:
            problems.append(f"a certificate went to {user_id!r}, who is not the customer")
            continue
        reservations = [before["reservations"][r] for r in user["reservations"]]
        eligible = user["membership"] in ("silver", "gold") or any(
            r["insurance"] == "yes" or r["cabin"] == "business" for r in reservations
        )
        if not eligible:
            problems.append(
                f"a certificate of {amount} went to a {user['membership']} member with no "
                "insurance and no business reservation"
            )
            continue
        allowed = set()
        for r in reservations:
            statuses, passengers = _statuses(before, r), len(r["passengers"])
            if "cancelled" in statuses:
                allowed.add(CANCELLED_PER_PASSENGER * passengers)
            if "delayed" in statuses:
                allowed.add(DELAYED_PER_PASSENGER * passengers)
        if amount not in allowed:
            problems.append(
                f"a certificate of {amount} matches no cancelled or delayed flight of the "
                f"customer (allowed: {', '.join(map(str, sorted(allowed))) or 'none'})"
            )
    return problems


def flight_change_problems(before: State, after: State, trace: Trace) -> list[str]:
    problems = []
    for event in _successful(trace, "update_reservation_flights"):
        arguments = event["arguments"]
        reservation = before["reservations"].get(arguments.get("reservation_id"))
        if reservation is None:
            continue
        name = reservation["reservation_id"]
        if reservation["cabin"] == "basic_economy":
            problems.append(f"the flights of {name}, a basic economy reservation, were changed")
        legs = [before["flights"][leg["flight_number"]] for leg in arguments.get("flights") or []]
        if not legs:
            continue
        if legs[0]["origin"] != reservation["origin"]:
            problems.append(
                f"{name} now starts at {legs[0]['origin']}, not {reservation['origin']}"
            )
        if reservation["destination"] not in {leg["destination"] for leg in legs}:
            problems.append(f"{name} no longer reaches {reservation['destination']}")
        end = reservation["origin"] if reservation["flight_type"] == "round_trip" else None
        end = end or reservation["destination"]
        if legs[-1]["destination"] != end:
            problems.append(f"{name} now ends at {legs[-1]['destination']}, not {end}")
    return problems
