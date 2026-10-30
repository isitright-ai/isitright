"""Smaller core pieces: edge values, evidence helpers, replay artifacts, comparators, oracles."""

from __future__ import annotations

from pathlib import Path

import pytest

from isitright.core.compare import JsonComparator
from isitright.core.constraints import Domain
from isitright.core.evidence import (
    AttributionStatus,
    DivergenceStatus,
    FailOn,
    headline_for,
    policy_triggered,
    rank_cases,
    safe_detail,
    totals_of,
)
from isitright.core.oracles import Outcome, Role, controls_status
from isitright.core.replay import ReplayArtifact, load_artifact, replay, write_artifact
from isitright.core.subjects import Cost
from isitright.core.values import edge_values
from tests.factories import make_case


def test_edge_values_cover_each_type_and_respect_a_declared_domain() -> None:
    floats = edge_values("float")
    assert 0.0 in floats and any(v < 0 for v in floats) and any(abs(v) >= 1e6 for v in floats)
    assert "" in edge_values("text") and any(not v.isascii() for v in edge_values("text"))
    assert 0 in edge_values("int") and edge_values("date") == []
    positive = edge_values("float", Domain(minimum=0, min_exclusive=True))
    assert positive and all(v > 0 for v in positive)
    assert edge_values("int", Domain(values=(0,))) == [0]
    assert edge_values("float") == edge_values("float")  # derandomized: the same every time


def test_edge_values_are_a_family_that_only_touches_hinted_fields() -> None:
    from isitright.core.families import default_mutators
    from isitright.core.hints import Hint, Hints
    from isitright.core.mutations import World
    from tests.test_core import base_state, spec

    mutator = next(m for m in default_mutators() if m.family == "edge_value")
    world = World(base_state())
    assert list(mutator.propose(spec(), world, Hints())) == []
    hinted = Hints([Hint(kind="threshold", args={"path": "orders.total", "value": 50})])
    mutations = list(mutator.propose(spec(), world, hinted))
    assert mutations and {m.touches[0] for m in mutations} == {"orders.total"}


def test_headlines_and_error_text() -> None:
    assert headline_for(DivergenceStatus.INCONCLUSIVE, "no run completed").startswith(
        "Inconclusive:"
    )
    with pytest.raises(ValueError, match="never says"):
        headline_for(DivergenceStatus.INCONCLUSIVE, "the test failed")
    assert safe_detail("the test failed") == "see the errors list"
    assert safe_detail("timed   out\nafter 3s") == "timed out after 3s"


def test_ranking_totals_and_ci_policy() -> None:
    domain = make_case(
        "d", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL", "DOMAIN_VALIDATED")
    )
    structural = make_case("s", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL",))
    none = make_case("n", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ())
    inconclusive = make_case("i", DivergenceStatus.INCONCLUSIVE, ())
    assert [c.case_id for c in rank_cases([none, inconclusive, structural, domain])] == [
        "d",
        "s",
        "i",
        "n",
    ]
    totals = totals_of([domain, structural, none])
    assert totals.cases == 3
    assert totals.by_validity == {"DOMAIN_VALIDATED": 1, "NOT_FOUND_WITHIN_BUDGET": 0} or (
        totals.by_validity["DOMAIN_VALIDATED"] == 1 and totals.by_validity["STRUCTURAL"] == 1
    )
    assert policy_triggered(domain, FailOn.DOMAIN_COUNTEREXAMPLE)
    assert not policy_triggered(structural, FailOn.DOMAIN_COUNTEREXAMPLE)
    assert policy_triggered(structural, FailOn.ANY_COUNTEREXAMPLE)
    assert not policy_triggered(none, FailOn.ANY_COUNTEREXAMPLE)
    assert domain.attribution_status is AttributionStatus.UNDETERMINED


def test_replay_artifacts_round_trip_and_name_what_differs(tmp_path: Path) -> None:
    artifact = ReplayArtifact(
        pack="x", case_id="c", world={"a": 1}, expected={"result": [1, 2], "disagrees": True}
    )
    path = tmp_path / "replay.json"
    digest = write_artifact(path, artifact)
    assert len(digest) == 64 and load_artifact(path) == artifact
    assert replay(artifact, lambda a: {"result": [1, 2], "disagrees": True}).reproduced
    outcome = replay(artifact, lambda a: {"result": [1], "disagrees": True})
    assert not outcome.reproduced and "result" in outcome.details[0]


def test_comparators_and_controls() -> None:
    comparator = JsonComparator(ignore_keys=frozenset({"id"}))
    assert comparator.compare(
        {"id": 1, "a": [{"id": 2, "b": 3}]}, {"id": 9, "a": [{"b": 3}]}
    ).matches
    result = comparator.compare({"a": 1}, {"a": 2})
    assert not result.matches and "expected" in (result.difference or "")
    assert controls_status([])[0] == "NOT_APPLICABLE"
    met = [(Role.CONTROL, [Outcome.MET, Outcome.NOT_MET]), (Role.TRAP, [Outcome.MET])]
    assert controls_status(met)[0] == "DISCRIMINATING"
    never = [(Role.CONTROL, [Outcome.NOT_MET]), (Role.CONTROL, [Outcome.MET])]
    assert controls_status(never)[0] == "NOT_DISCRIMINATING"


def test_cost_adds() -> None:
    total = Cost(1, 2, 0.5, 1.0) + Cost(3, 4, 0.25, 2.0)
    assert (total.input_tokens, total.output_tokens, total.money, total.seconds) == (
        4,
        6,
        0.75,
        3.0,
    )
