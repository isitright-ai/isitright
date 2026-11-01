"""The tau2 airline entity model (a proposed fixture) against a local tau2 checkout, if present."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AIRLINE = Path(__file__).parents[1] / "examples" / "agents" / "airline"
sys.path.insert(0, str(AIRLINE))

import airline_model as model  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (model.DOMAIN / "db.json").is_file(), reason="no tau2 checkout (set ISITRIGHT_TAU2_DIR)"
)


def test_the_hints_resolve_in_the_entity_model_and_state_is_valid() -> None:
    state = model.base_state("1")
    assert model.spec().validate(state).status.value == "VALID"
    model.hints("1").validate(model.SCHEMA)
    kinds = {h.name: h.kind for h in model.hints("1")}
    assert kinds["airline_cancelled"] == "gate" and kinds["booked_within_24h"] == "threshold"


def test_a_generated_world_with_a_cancelled_segment_is_written_back_to_the_database() -> None:
    from isitright.core.families import default_mutators
    from isitright.core.mutations import World
    from isitright.core.search import Evaluation, Verdict, search
    from isitright.core.stochastic import Budget

    spec, hints = model.spec(), model.hints("1")
    found = []

    def collect(candidate: object, validity: object) -> Evaluation:
        found.append(candidate.world)  # type: ignore[attr-defined]
        return Evaluation(Verdict.DISAGREE)

    search(
        spec,
        World(model.base_state("1")),
        hints,
        default_mutators(),
        collect,
        budget=Budget(attempts=400),
        depth=1,
        stop_on_first=False,
    )
    cancelled = next(
        w
        for w in found
        if len(w.path) == 1
        and any(e["status"] == "cancelled" for e in w.state.entities("flight_dates"))
        and not any(
            e["status"] == "cancelled" for e in model.base_state("1").entities("flight_dates")
        )
    )
    db = model.load_db()
    patched = model.apply_state(db, cancelled.state)
    changed = [
        e["id"] for e in cancelled.state.entities("flight_dates") if e["status"] == "cancelled"
    ]
    flight, date = changed[0].split("|")
    assert patched["flights"][flight]["dates"][date] == {"status": "cancelled"}
    assert db["flights"][flight]["dates"][date] != {"status": "cancelled"}  # the input is untouched
    base = model.apply_state(db, model.base_state("1"))
    assert base["reservations"] == db["reservations"]  # writing the base back changes nothing
    unchanged = {k: v for k, v in patched["flights"].items() if k != flight}
    assert unchanged == {k: v for k, v in db["flights"].items() if k != flight}
    with pytest.raises(ValueError, match="needs the fields"):
        bad = model.base_state("1")
        first = bad.entities("flight_dates")[0]
        other = "delayed" if first["status"] != "delayed" else "on time"
        model.apply_state(db, bad.evolve({"flight_dates": [{**first, "status": other}]}))
