"""The tau2 airline domain as an entity model with hints, for the 0.5 rediscovery check.

The entity schema comes from tau2's `data_model.py` (the shapes of users, reservations and flight
dates). The hints come from the policy text (`policy.md`, "Cancel flight"), the tool schemas
(`tools.py`: `cancel_reservation`, `get_reservation_details`, `get_flight_status`) and a task's own
text (its user id). They were written before the S1 worlds or findings were read; see the 0.5
notes (`REVIEW.md`) for who wrote them (the S1 author's session wrote them, which the roadmap says
should ideally not be the case).

No agent runs here: this only builds a world spec and hints, so the core can generate worlds.

    ISITRIGHT_TAU2_DIR=C:/Code/tau2-bench   (a checkout of sierra-research/tau2-bench)
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.spec import WorldSpec
from isitright.core.world import State

TAU2 = Path(os.environ.get("ISITRIGHT_TAU2_DIR", "C:/Code/tau2-bench"))
DOMAIN = TAU2 / "data" / "tau2" / "domains" / "airline"
NOW = "2024-05-15T15:00:00"
"""The airline tools use this simulated clock (`_get_datetime`); 24 hours before it: 05-14 15:00."""
STATUSES = ["available", "on time", "delayed", "flying", "landed", "cancelled"]

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="users",
            key="user_id",
            fields=[FieldSpec(name="user_id"), FieldSpec(name="membership", optional=True)],
        ),
        CollectionSpec(
            name="reservations",
            key="reservation_id",
            fields=[
                FieldSpec(name="reservation_id"),
                FieldSpec(name="user_id"),
                FieldSpec(name="cabin", enum=["basic_economy", "economy", "business"]),
                FieldSpec(name="created_at", type="datetime"),
                FieldSpec(name="insurance", enum=["yes", "no"]),
                FieldSpec(name="status", optional=True, nullable=True),
                FieldSpec(name="origin"),
                FieldSpec(name="destination"),
                FieldSpec(name="flight_type"),
                FieldSpec(name="passengers", type="json"),
                FieldSpec(name="payment_history", type="json"),
                FieldSpec(name="total_baggages", type="int"),
                FieldSpec(name="nonfree_baggages", type="int"),
                FieldSpec(
                    name="flights",
                    type="json",
                    shape={
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "flight_number": {"type": "string"},
                                "date": {"type": "string"},
                                "price": {"type": "number", "minimum": 0},
                            },
                        },
                    },
                ),
            ],
        ),
        CollectionSpec(
            name="flight_dates",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="flight_number"),
                FieldSpec(name="date"),
                FieldSpec(name="status", enum=STATUSES),
            ],
        ),
    ]
)
KEYS = SCHEMA.keys()


def load_db() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DOMAIN / "db.json").read_text(encoding="utf-8"))
    return data


def task_user(task_id: str) -> str:
    """The user id a task's own text gives ("Your user id is '...'")."""
    tasks = json.loads((DOMAIN / "tasks.json").read_text(encoding="utf-8"))
    task = next(t for t in tasks if str(t["id"]) == str(task_id))
    text = task["user_scenario"]["instructions"]["known_info"] or ""
    marker = "user id is"
    start = text.index(marker) + len(marker)
    return text[start:].strip().split()[0].strip("'.\"")


def base_state(task_id: str) -> State:
    """The user, their reservations and the flight dates those reservations use."""
    db = load_db()
    user_id = task_user(task_id)
    user = db["users"][user_id]
    reservations = [db["reservations"][rid] for rid in user["reservations"]]
    dates: dict[str, dict[str, Any]] = {}
    for reservation in reservations:
        for leg in reservation["flights"]:
            status = db["flights"][leg["flight_number"]]["dates"][leg["date"]]["status"]
            key = f"{leg['flight_number']}|{leg['date']}"
            dates[key] = {
                "id": key,
                "flight_number": leg["flight_number"],
                "date": leg["date"],
                "status": status,
            }
    return State(
        {
            "users": ({"user_id": user_id},),
            "reservations": tuple(copy.deepcopy(r) for r in reservations),
            "flight_dates": tuple(dates.values()),
        },
        KEYS,
    )


def hints(task_id: str) -> Hints:
    """Declared from the policy text, the tool schemas and the task's user id."""
    user_id = task_user(task_id)
    return Hints(
        [
            Hint(
                kind="lookup",  # the task text: "Your user id is ..."
                name="user",
                provenance=Provenance.DECLARED,
                args={"collection": "users", "fields": ["user_id"], "value": [user_id]},
            ),
            Hint(
                kind="scope",  # get_user_details lists the user's reservations; act only on them
                name="own_reservations",
                provenance=Provenance.DECLARED,
                args={"collection": "reservations", "where": "user_id in $user.user_id"},
            ),
            Hint(
                kind="gate",  # policy: "The flight is cancelled by airline"
                name="airline_cancelled",
                provenance=Provenance.DECLARED,
                args={
                    "collection": "flight_dates",
                    "field": "status",
                    "allows": ["cancelled"],
                    "action": "cancel_reservation",
                },
            ),
            Hint(
                kind="gate",  # policy: "It is a business flight"
                name="business_cabin",
                provenance=Provenance.DECLARED,
                args={
                    "collection": "reservations",
                    "field": "cabin",
                    "allows": ["business"],
                    "action": "cancel_reservation",
                },
            ),
            Hint(
                kind="gate",  # policy: "The user has travel insurance and the reason is covered"
                name="insured",
                provenance=Provenance.DECLARED,
                args={
                    "collection": "reservations",
                    "field": "insurance",
                    "allows": ["yes"],
                    "action": "cancel_reservation",
                },
            ),
            Hint(
                kind="threshold",  # policy: "The booking was made within the last 24 hrs"
                # Whether exactly 24 hours counts as "within" is not in the policy, so the hint
                # does not say (no inclusive/holds) and the world on the cut-off is not judged.
                name="booked_within_24h",
                provenance=Provenance.DECLARED,
                args={"path": "reservations.created_at", "value": "2024-05-14T15:00:00"},
            ),
        ]
    )


def spec() -> WorldSpec:
    return WorldSpec(id="airline", schema=SCHEMA, policy=(DOMAIN / "policy.md").read_text("utf-8"))


def slice_db(db: dict[str, Any], user_id: str) -> dict[str, Any]:
    """The database a scenario serves: every flight, the user and the user's reservations.

    Other users and reservations are left out (the tools never need them for this user's tasks,
    and a whole database would make every run record seven megabytes of state).
    """
    user = db["users"][user_id]
    return {
        "flights": db["flights"],
        "users": {user_id: user},
        "reservations": {rid: db["reservations"][rid] for rid in user["reservations"]},
    }


def applicable(db: dict[str, Any], state: State) -> list[str]:
    """Why a state cannot be written into the database, empty when it can.

    A flight date must exist, and its status may change only to ``cancelled`` (the other statuses
    carry times and seat counts the entity model does not hold).
    """
    problems = []
    users = state.entities("users")
    if len(users) != 1 or users[0]["user_id"] not in db["users"]:
        problems.append("the world must have exactly the customer the database serves")
    for entity in state.entities("flight_dates"):
        known = db["flights"].get(entity["flight_number"], {}).get("dates", {}).get(entity["date"])
        if known is None:
            problems.append(f"flight date {entity['id']} does not exist in the database")
        elif known["status"] != entity["status"] and entity["status"] != "cancelled":
            problems.append(f"flight date {entity['id']}: status {entity['status']!r} not writable")
    return problems


def apply_state(db: dict[str, Any], state: State) -> dict[str, Any]:
    """A copy of the tau2 airline database with a generated world's changes written back.

    Written: flight-date statuses (``cancelled`` only, as `applicable` says), and every field of
    each reservation, including added and removed ones (the user's reservation list follows). The
    copy shares the untouched parts of ``db`` with it, so it is cheap, and nothing here mutates
    ``db``. The result is what a harness loads into tau2's environment, for example
    ``FlightDB.model_validate(apply_state(...))``.
    """
    patched = {name: dict(part) for name, part in db.items()}
    for entity in state.entities("flight_dates"):
        flight = patched["flights"][entity["flight_number"]]
        dates = flight["dates"]
        if entity["status"] == "cancelled":
            if dates[entity["date"]] != {"status": "cancelled"}:
                patched["flights"][entity["flight_number"]] = {
                    **flight,
                    "dates": {**dates, entity["date"]: {"status": "cancelled"}},
                }
        elif dates[entity["date"]]["status"] != entity["status"]:
            raise ValueError(
                f"flight date {entity['id']}: changing a status to {entity['status']!r} needs the "
                "fields of that status, which the entity model does not hold"
            )
    scoped = {e["user_id"] for e in state.entities("users")}
    kept = {e["reservation_id"] for e in state.entities("reservations")}
    for rid in [r for r, v in patched["reservations"].items() if v["user_id"] in scoped]:
        if rid not in kept:
            del patched["reservations"][rid]
    for entity in state.entities("reservations"):
        patched["reservations"][entity["reservation_id"]] = copy.deepcopy(entity)
    for uid in scoped:
        patched["users"][uid] = {
            **patched["users"][uid],
            "reservations": [r for r, v in patched["reservations"].items() if v["user_id"] == uid],
        }
    return patched
