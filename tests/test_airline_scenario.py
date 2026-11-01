"""The tau2 airline scenario: tau2's own tools on a generated world, a policy-based oracle.

Skipped without a tau2 checkout (set ISITRIGHT_TAU2_DIR) and the tau2 package. The scripted agents
and the oracle are the host author's, so this shows the machinery works on tau2's tools, not that
the oracle is independent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

AIRLINE = Path(__file__).parents[1] / "examples" / "agents" / "airline"
sys.path.insert(0, str(AIRLINE))

import airline_model as model  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (model.DOMAIN / "db.json").is_file() or importlib.util.find_spec("tau2") is None,
    reason="no tau2 checkout or package",
)

from isitright.core.mutations import SetField, World, apply_edits  # noqa: E402
from isitright.core.oracles import Role  # noqa: E402
from isitright.packs.mcp.audit import run_scenario  # noqa: E402
from isitright.packs.mcp.generate import generate_worlds  # noqa: E402
from isitright.packs.mcp.model import load_scenario  # noqa: E402
from isitright.packs.mcp.oracle import reference_outcome  # noqa: E402
from isitright.packs.mcp.replay import replay_report  # noqa: E402
from isitright.packs.mcp.runtime import ServiceRuntime  # noqa: E402

REF = f"{AIRLINE / 'scenario.py'}:SCENARIO"
AGENT = f'"{sys.executable}" "{AIRLINE / "scripted_agent.py"}"'
ATTEMPTS = 120


@pytest.fixture(scope="module")
def scenario():  # type: ignore[no-untyped-def]
    return load_scenario(REF)


def _cancel_first_segment(scenario) -> World:  # type: ignore[no-untyped-def]
    target = next(
        r for r in scenario.base.entities("reservations") if r["reservation_id"] == "Q69X3R"
    )
    leg = target["flights"][0]
    key = f"{leg['flight_number']}|{leg['date']}"
    edit = SetField(collection="flight_dates", key=key, path=["status"], value="cancelled")
    return World(apply_edits(scenario.base, [edit]))


def test_the_tools_are_tau2s_own_and_the_state_is_a_slice_of_its_database(scenario) -> None:  # type: ignore[no-untyped-def]
    names = {t.name for t in scenario.tools}
    assert {"get_reservation_details", "cancel_reservation", "get_flight_status"} <= names
    writes = {t.name for t in scenario.tools if t.writes}
    assert "cancel_reservation" in writes and "get_flight_status" not in writes
    runtime = ServiceRuntime.for_world(scenario, World(scenario.base))
    assert set(runtime.service["users"]) == {"mia_li_3668"} or len(runtime.service["users"]) == 1
    assert len(runtime.service["flights"]) == 300 and len(runtime.service["reservations"]) < 20
    details = runtime.call("get_reservation_details", {"reservation_id": "Q69X3R"})
    assert "Q69X3R" in details
    with pytest.raises(ValueError):
        runtime.call("get_reservation_details", {"reservation_id": "NOPE00"})


def test_the_base_world_is_a_trap_and_a_cancelled_segment_makes_it_a_control(scenario) -> None:  # type: ignore[no-untyped-def]
    assert reference_outcome(scenario, World(scenario.base)).role is Role.TRAP
    world = _cancel_first_segment(scenario)
    reference = reference_outcome(scenario, world)
    assert reference.role is Role.CONTROL and reference.write_calls
    assert reference.after is not None and reference.after["reservations"]["Q69X3R"]["status"] == (
        "cancelled"
    )
    runtime = ServiceRuntime.for_world(scenario, world)
    runtime.call("cancel_reservation", {"reservation_id": "Q69X3R"})  # a write syncs the state
    assert runtime.service["reservations"]["Q69X3R"]["status"] == "cancelled"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):  # type: ignore[no-untyped-def]
    scenario = load_scenario(REF)
    found, _ = generate_worlds(scenario, attempts=ATTEMPTS)
    base_leg = next(
        r for r in scenario.base.entities("reservations") if r["reservation_id"] == "Q69X3R"
    )["flights"][0]
    first = f"{base_leg['flight_number']}|{base_leg['date']}"
    cancelled = next(
        w
        for w in found
        if len(w.world.path) == 1
        and any(
            e["id"] == first and e["status"] == "cancelled"
            for e in w.world.state.entities("flight_dates")
        )
    )
    trap = next(w for w in found if w.role is Role.TRAP and len(w.world.path) == 1)
    out = {"worlds": (cancelled, trap)}
    for mode in ("careful", "careless", "refuse"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("AIRLINE_AGENT_MODE", mode)
            output = tmp_path_factory.mktemp(mode) / "out"
            out[mode] = (
                run_scenario(
                    scenario_ref=REF,
                    agent_command=AGENT,
                    output_dir=output,
                    worlds="generated",
                    attempts=ATTEMPTS,
                    k=1,
                    sequential=False,
                    only=[cancelled.id, trap.id],
                    trust_code=True,
                    timeout_seconds=300,
                ),
                output,
            )
    return out


def test_the_agents_are_told_apart_on_tau2s_tools(runs) -> None:  # type: ignore[no-untyped-def]
    cancelled, trap = runs["worlds"]
    assert cancelled.role is Role.CONTROL and trap.role is Role.TRAP
    findings = {
        m: {f.world_id for f in runs[m][0].cases[0].findings}
        for m in ("careful", "careless", "refuse")
    }
    assert findings["careful"] == set()
    assert findings["careless"] == {trap.id}  # cancels where the policy gives no basis
    assert findings["refuse"] == {cancelled.id}  # does nothing where the airline cancelled a flight
    careless = runs["careless"][0].cases[0]
    assert careless.execution_fidelity.found_on == "SIMULATED"
    assert next(w for w in careless.worlds if w.id == cancelled.id).oracle_outcome == "MET"


def test_a_report_on_the_airline_scenario_replays(runs) -> None:  # type: ignore[no-untyped-def]
    report, output = runs["careless"]
    outcomes = replay_report(report, None, output)
    assert outcomes and all(o.reproduced for o in outcomes), [
        o for o in outcomes if not o.reproduced
    ]
