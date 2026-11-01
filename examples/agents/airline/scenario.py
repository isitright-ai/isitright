"""The tau2 airline domain as an isitright scenario: tau2's own tools, a policy-based oracle.

What is tau2's: the tools (`AirlineTools`, run unchanged on a `FlightDB` built from a generated
world), their schemas and descriptions, the database and the policy. What is ours: the entity
model and hints (`airline_model.py`, reviewed separately), the layout that writes a generated
world into the database, and the oracle below. The oracle is written from the policy's "Cancel
flight" section, by the same author as the host, so a finding is evidence for review, not a
verdict.

The task is cancellation: the customer of a tau2 task wants one reservation cancelled, and the
right behavior depends on the policy's four conditions and on whether a segment was already flown.
Choose the task and the reservation with environment variables (read when the scenario loads, in
the host process too):

    AIRLINE_TASK_ID        a tau2 airline task id (default 1)
    AIRLINE_RESERVATION    the reservation the customer wants cancelled; the default is the one
                           S1's hand-checked table names for that task (S1's worlds.py)
    AIRLINE_REASON         the reason the customer gives: change_of_plan (default),
                           airline_cancelled or covered_by_insurance. Only the last lets travel
                           insurance justify a cancellation.
    ISITRIGHT_TAU2_DIR     a checkout of sierra-research/tau2-bench (default C:/Code/tau2-bench)

    isitright agents run --trust-code --scenario examples/agents/airline/scenario.py:SCENARIO ...

The service state is a slice of tau2's database (every flight, the customer, the customer's
reservations), because the whole database is seven megabytes and every run records its state.
The tools therefore do not see other customers.
"""

from __future__ import annotations

import copy
import json
import os
import sys

os.environ.setdefault(
    "LOGURU_LEVEL", "ERROR"
)  # tau2 logs debug lines; the host's stdout is the protocol
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import airline_model as model
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.airline.tools import AirlineTools
from tau2.environment.environment import Environment

from isitright.core.constraints import PythonConstraint
from isitright.core.hosts import Fidelity
from isitright.core.spec import ToolSpec, WorldSpec
from isitright.core.world import State
from isitright.packs.mcp.model import (
    Invariant,
    Layout,
    McpScenario,
    ScenarioOracle,
    ToolDef,
)

NOW = datetime(2024, 5, 15, 15, 0, 0)
FLOWN = {"landed", "flying"}
# The reservation each task is about, from S1's hand-checked table (worlds.py in the S1 harness).
DEFAULT_RESERVATIONS = {
    "0": "EHGLP3",
    "1": "Q69X3R",
    "9": "IFOYYZ",
    "26": "3FRNFB",
    "28": "SI5UKW",
    "41": "UDMOP1",
    "45": "PEP4E0",
    "48": "3RK2T9",
    "49": "3RK2T9",
}
RESERVATION_FIELDS = (
    "reservation_id",
    "user_id",
    "cabin",
    "created_at",
    "insurance",
    "status",
    "origin",
    "destination",
    "flight_type",
    "flights",
    "passengers",
    "payment_history",
    "total_baggages",
    "nonfree_baggages",
)
REASONS = ("change_of_plan", "airline_cancelled", "covered_by_insurance")


class AirlineService(dict[str, Any]):
    """The database as a dict, with the validated tau2 database cached beside it.

    Handlers work on the validated `FlightDB`; after a tool that writes, ``sync`` replaces the dict
    with the database's dump, so the state the host records and the oracle reads is current.
    """

    _db: FlightDB | None = None

    def database(self) -> FlightDB:
        if self._db is None:
            self._db = FlightDB.model_validate(dict(self))
        return self._db

    def sync(self) -> None:
        dump = self.database().model_dump(mode="json")
        self.clear()
        self.update(dump)

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return copy.deepcopy(dict(self), memo)


class AirlineLayout(Layout):
    """Writes a generated world into the sliced tau2 database."""

    def to_service(self, state: State) -> Any:
        return AirlineService(model.apply_state(_slice(_user(state)), state))

    def from_service(self, data: Any, keys: Any) -> State:
        raise NotImplementedError("this scenario has no timers: state is never read back")


def _user(state: State) -> str:
    """The customer of a world. A world without one cannot be served (it is rejected as invalid)."""
    users = state.entities("users")
    return (
        str(users[0]["user_id"])
        if users
        else model.task_user(os.environ.get("AIRLINE_TASK_ID", "1"))
    )


@cache
def _slice(user_id: str) -> dict[str, Any]:
    return model.slice_db(model.load_db(), user_id)


def _tools() -> AirlineTools:
    return AirlineTools(FlightDB(flights={}, users={}, reservations={}))


def _handler(name: str) -> Any:
    def handle(state: AirlineService, arguments: dict[str, Any]) -> Any:
        tools = AirlineTools(state.database())
        result = Environment.to_json_str(tools.use_tool(name, **arguments))
        if tools.tool_mutates_state(name):
            state.sync()
        return result if isinstance(result, str) else json.dumps(result)

    return handle


def _tool_defs() -> tuple[list[ToolDef], list[ToolSpec]]:
    tools = _tools()
    defs, specs = [], []
    reservation = [f"reservations.{f}" for f in RESERVATION_FIELDS]
    exposes = {
        "get_reservation_details": reservation,
        "get_user_details": ["users.user_id"],
        "get_flight_status": ["flight_dates.status"],
        "search_direct_flight": ["flight_dates.status"],
        "search_onestop_flight": ["flight_dates.status"],
    }
    for name, tool in tools.get_tools().items():
        function = tool.openai_schema["function"]
        writes = tools.tool_mutates_state(name)
        defs.append(
            ToolDef(name, function["description"], function["parameters"], _handler(name), writes)
        )
        specs.append(ToolSpec(name=name, writes=writes, exposes=exposes.get(name, [])))
    return defs, specs


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def build(task_id: str, reservation: str, reason: str) -> McpScenario:
    tasks = json.loads((model.DOMAIN / "tasks.json").read_text(encoding="utf-8"))
    task = next(t for t in tasks if str(t["id"]) == task_id)
    instructions = task["user_scenario"]["instructions"]
    text = f"{instructions['reason_for_call']}\n{instructions['known_info'] or ''}".strip()
    defs, specs = _tool_defs()

    def reference(call: Any) -> None:
        """The policy's "Cancel flight" section, applied by a careful agent."""
        details = call("get_reservation_details", reservation_id=reservation)
        if details.get("status") == "cancelled":
            return
        statuses = [
            call("get_flight_status", flight_number=leg["flight_number"], date=leg["date"])["text"]
            for leg in details["flights"]
        ]
        if any(s in FLOWN for s in statuses):
            return  # a flown segment: the agent cannot cancel (it transfers)
        within_day = (NOW - _instant(details["created_at"])).total_seconds() <= 24 * 3600
        insured = details["insurance"] == "yes" and reason == "covered_by_insurance"
        if within_day or "cancelled" in statuses or details["cabin"] == "business" or insured:
            call("cancel_reservation", reservation_id=reservation)

    def cancelled(state: dict[str, Any]) -> list[str]:
        return sorted(r for r, v in state["reservations"].items() if v.get("status") == "cancelled")

    def only_the_target(before: dict[str, Any], after: dict[str, Any], trace: Any) -> list[str]:
        newly = set(cancelled(after)) - set(cancelled(before))
        return [
            f"{r} was cancelled but the customer asked about {reservation}"
            for r in sorted(newly - {reservation})
        ]

    def not_a_flown_segment(before: dict[str, Any], after: dict[str, Any], trace: Any) -> list[str]:
        if reservation not in set(cancelled(after)) - set(cancelled(before)):
            return []
        legs = before["reservations"][reservation]["flights"]
        flown = [
            leg["flight_number"]
            for leg in legs
            if before["flights"][leg["flight_number"]]["dates"][leg["date"]]["status"] in FLOWN
        ]
        return (
            [f"cancelled a reservation with a flown segment: {', '.join(flown)}"] if flown else []
        )

    oracle = ScenarioOracle(
        name="airline_cancellation_policy",
        invariants=[
            Invariant(
                "only_the_target_is_cancelled",
                "no reservation other than the one the customer asked about is cancelled",
                only_the_target,
            ),
            Invariant(
                "no_cancel_after_a_flown_segment",
                "a reservation with a segment already flown is not cancelled",
                not_a_flown_segment,
            ),
        ],
        reference=reference,
        normalize=lambda state: cancelled(state),
        normalize_call=lambda tool, args: (tool, args),
        assumptions=[
            "the policy's four conditions are applied to the whole reservation: one cancelled "
            "segment is enough ('the flight is cancelled by airline')",
            f"the customer's reason is {reason!r}; insurance justifies cancelling only for "
            "'covered_by_insurance'",
            "the clock is the tools' fixed 2024-05-15 15:00",
        ],
        description="the reservations cancelled equal those the policy-based reference cancels",
    )
    spec = WorldSpec(
        id="airline",
        schema=model.SCHEMA,
        python_constraints=[
            PythonConstraint(
                "airline_world_is_writable",
                lambda state: model.applicable(
                    _slice(state.entities("users")[0]["user_id"]), state
                ),
                "the world can be written into the airline database",
                tier="STRUCTURAL",
            )
        ],
        tools=specs,
        policy=(model.DOMAIN / "policy.md").read_text(encoding="utf-8"),
    )
    return McpScenario(
        id=f"airline-task-{task_id}",
        task=text,
        spec=spec,
        tools=defs,
        base=model.base_state(task_id),
        layout=AirlineLayout(keyed=(), scalars=(), block="meta"),
        oracle=oracle,
        hints=model.hints(task_id),
        fidelity=Fidelity.SIMULATED,
    )


def _from_environment() -> McpScenario:
    task_id = os.environ.get("AIRLINE_TASK_ID", "1")
    reservation = os.environ.get("AIRLINE_RESERVATION") or DEFAULT_RESERVATIONS[task_id]
    reason = os.environ.get("AIRLINE_REASON", "change_of_plan")
    if reason not in REASONS:
        raise ValueError(f"AIRLINE_REASON must be one of {REASONS}")
    return build(task_id, reservation, reason)


SCENARIO = _from_environment()
