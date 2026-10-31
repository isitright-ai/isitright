# Proposed fixture: pending owner review
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
            "reservations": tuple(
                {
                    "reservation_id": r["reservation_id"],
                    "user_id": r["user_id"],
                    "cabin": r["cabin"],
                    "created_at": r["created_at"],
                    "insurance": r["insurance"],
                    "flights": r["flights"],
                    **({"status": r["status"]} if r.get("status") else {}),
                }
                for r in reservations
            ),
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
                name="booked_within_24h",
                provenance=Provenance.DECLARED,
                args={"path": "reservations.created_at", "value": "2024-05-14T15:00:00"},
            ),
        ]
    )


def spec() -> WorldSpec:
    return WorldSpec(id="airline", schema=SCHEMA, policy=(DOMAIN / "policy.md").read_text("utf-8"))


def apply_state(db: dict[str, Any], state: State) -> dict[str, Any]:
    """A copy of the tau2 airline database with a generated world's changes written back.

    Only what the entity model holds is written: flight-date statuses, and each reservation's
    cabin, creation time, insurance, status and flights. A cancelled flight date keeps no other
    field, as in tau2's own data. The result is what a harness loads into tau2's environment (for
    example ``FlightDB.model_validate(apply_state(...))``) to run an agent in the world.
    """
    import copy

    patched = copy.deepcopy(db)
    for entity in state.entities("flight_dates"):
        dates = patched["flights"][entity["flight_number"]]["dates"]
        if entity["status"] == "cancelled":
            dates[entity["date"]] = {"status": "cancelled"}
        elif dates[entity["date"]]["status"] != entity["status"]:
            raise ValueError(
                f"flight date {entity['id']}: changing a status to {entity['status']!r} needs the "
                "fields of that status, which the entity model does not hold"
            )
    for entity in state.entities("reservations"):
        target = patched["reservations"][entity["reservation_id"]]
        for name in ("cabin", "created_at", "insurance", "flights"):
            target[name] = copy.deepcopy(entity[name])
        if entity.get("status"):
            target["status"] = entity["status"]
        else:
            target.pop("status", None)
    return patched
