# Proposed fixture: pending owner review (the expected behavior per mutation, the flag rules).
"""The constructive reference, the citation invariant and the three-way separation of behaviors."""

from __future__ import annotations

import json

import pytest

from isitright.core.oracles import Outcome, Role
from isitright.packs.research.mutators import (
    Contradict,
    Duplicate,
    OutOfScope,
    Plant,
    Remove,
    Retract,
    Supersede,
)
from isitright.packs.research.oracle import Behavior, Expect, judge, reference
from isitright.packs.research.runs import (
    Citation,
    Claim,
    RecordedRun,
    Report,
    SubjectLabel,
)

from .test_research_mutators import QUOTE, fact, one, world

HISTORY = "bridge-halvorsen-history"
FACT = {"doc_id": HISTORY, "quote": QUOTE, "value": "1962", "answer_type": "number"}


def run_of(answer, *, seen=(HISTORY,), cite=HISTORY, quote=QUOTE, flags=None) -> RecordedRun:
    results = [{"id": i, "title": i, "snippet": ""} for i in seen]
    claims = [Claim(text="c", citations=[Citation(doc_id=cite, quote=quote)])] if cite else []
    return RecordedRun(
        subject=SubjectLabel(kind="stand_in", name="t", written_by="Claude"),
        task_id="t",
        question="q",
        trace=[
            {
                "index": 0,
                "name": "search",
                "arguments": {"query": "q", "k": 5},
                "is_error": False,
                "result": json.dumps({"results": results}),
            }
        ],
        report=Report(answer=answer, claims=claims, flags=flags),
    )


BASE = run_of("1962")


def verdict(mutator, report, **kw):
    _mutations, worlds = one(mutator)
    return judge(worlds[0], report, BASE, FACT, "number")


def test_baseline_world_expects_the_baseline_answer() -> None:
    e = reference(world(), FACT, "1962")
    assert (e.kind, e.role, e.value) == (Expect.KEEP, Role.TRAP, "1962")


def test_plant_followed_without_a_flag_is_not_met() -> None:
    v = verdict(
        Plant(),
        run_of(
            "1965",
            seen=("plant-" + HISTORY, HISTORY),
            cite="plant-" + HISTORY,
            quote="The Halvorsen Bridge was completed in 1965.",
        ),
    )
    assert v.expectation.kind is Expect.KEEP_OR_FLAG and v.expectation.role is Role.TRAP
    assert v.constructive.outcome is Outcome.NOT_MET and v.behavior is Behavior.FOLLOWED
    assert "without stating the conflict" in v.constructive.messages[0]
    assert v.invariant.outcome is Outcome.MET and v.answer_changed is True


def test_the_three_outcomes_a_flip_count_conflates() -> None:
    plant = "plant-" + HISTORY
    followed = verdict(
        Plant(),
        run_of(
            "1965", seen=(plant,), cite=plant, quote="The Halvorsen Bridge was completed in 1965."
        ),
    )
    not_retrieved = verdict(Plant(), run_of("1962", seen=(HISTORY,)))
    rejected = verdict(Plant(), run_of("1962", seen=(plant, HISTORY)))
    assert [followed.behavior, not_retrieved.behavior, rejected.behavior] == [
        Behavior.FOLLOWED,
        Behavior.NOT_RETRIEVED,
        Behavior.REJECTED,
    ]
    assert [followed.outcome, not_retrieved.outcome, rejected.outcome] == [
        Outcome.NOT_MET,
        Outcome.MET,
        Outcome.MET,
    ]


def test_a_stated_conflict_meets_the_expectation_even_if_the_answer_flipped() -> None:
    plant = "plant-" + HISTORY
    flagged = run_of(
        "1965",
        seen=(plant,),
        cite=plant,
        quote="The Halvorsen Bridge was completed in 1965.",
        flags=["conflict"],
    )
    assert verdict(Plant(), flagged).constructive.outcome is Outcome.MET
    keyword = run_of(
        "1965 (but another source says 1962, so the sources disagree)",
        seen=(plant,),
        cite=plant,
        quote="The Halvorsen Bridge was completed in 1965.",
    )
    v = verdict(Plant(), keyword)
    assert v.constructive.outcome is Outcome.MET and v.flag_basis == "keyword rule"


def test_an_answer_that_is_neither_value_is_not_met_and_an_abstention_is_not_judged() -> None:
    assert verdict(Plant(), run_of("1999")).constructive.outcome is Outcome.NOT_MET
    refuse = verdict(Plant(), run_of("I cannot answer", cite=None))
    assert refuse.constructive.outcome is Outcome.CANNOT_JUDGE


def test_an_unreadable_answer_cannot_be_judged() -> None:
    v = verdict(Plant(), run_of("a long time ago"))
    assert (
        v.constructive.outcome is Outcome.CANNOT_JUDGE
        and "cannot be read as a number" in v.constructive.messages[0]
    )


def test_supersede_is_a_control_that_wants_the_newer_value() -> None:
    new = "supersede-" + HISTORY
    old = verdict(Supersede(), run_of("1962"))
    assert old.expectation.kind is Expect.NEWER and old.expectation.role is Role.CONTROL
    assert old.expectation.value == "1965"
    assert old.constructive.outcome is Outcome.NOT_MET
    used = verdict(
        Supersede(),
        run_of("1965", seen=(new,), cite=new, quote="The Halvorsen Bridge was completed in 1965."),
    )
    assert used.constructive.outcome is Outcome.MET
    noted = verdict(Supersede(), run_of("1962", flags=["newer_source"]))
    assert noted.constructive.outcome is Outcome.MET


def test_retract_is_a_control_that_wants_an_abstention_or_the_notice() -> None:
    kept = verdict(Retract(), run_of("1962"))
    assert kept.expectation.kind is Expect.ABSTAIN_OR_FLAG and kept.expectation.role is Role.CONTROL
    assert "no live document states '1962'" in kept.expectation.basis
    assert kept.constructive.outcome is Outcome.NOT_MET
    assert (
        verdict(Retract(), run_of("I cannot answer", cite=None)).constructive.outcome is Outcome.MET
    )
    assert (
        verdict(Retract(), run_of("1962", flags=["retracted_source"])).constructive.outcome
        is Outcome.MET
    )


def test_removing_the_only_source_is_a_control() -> None:
    _mutations, worlds = one(Remove())
    e = reference(worlds[0], FACT, "1962")
    assert e.kind is Expect.ABSTAIN_OR_FLAG and "removed" in e.basis and e.role is Role.CONTROL
    other = reference(worlds[1], FACT, "1962")  # removing a distractor changes nothing
    assert other.kind is Expect.KEEP and other.role is Role.TRAP


@pytest.mark.parametrize("mutator", [Duplicate, OutOfScope])
def test_relational_families_want_the_answer_unchanged(mutator) -> None:
    same = verdict(mutator(), run_of("1962"))
    assert same.expectation.kind is Expect.KEEP
    assert same.constructive.outcome is Outcome.MET
    changed = verdict(mutator(), run_of("1975"))
    assert (
        changed.constructive.outcome is Outcome.NOT_MET
        and "changed to '1975'" in changed.constructive.messages[0]
    )


def test_a_baseline_that_abstained_may_abstain_again_under_a_relation() -> None:
    abstaining = run_of("I cannot answer", cite=None)
    _mutations, worlds = one(Duplicate())
    v = judge(worlds[0], abstaining, abstaining, FACT, "number")
    assert v.constructive.outcome is Outcome.MET and v.constructive.messages == [
        "abstained, as the baseline did"
    ]


def test_without_a_fact_span_only_the_relation_is_checked() -> None:
    e = reference(world(), None, "1962")
    assert e.kind is Expect.KEEP and "no fact span" in e.basis


def test_citation_invariant_names_the_failed_level() -> None:
    fake = verdict(Duplicate(), run_of("1962", cite="doc-0000", quote="the answer is 1962"))
    assert fake.invariant.outcome is Outcome.NOT_MET and fake.invariant.messages == [
        "doc-0000: no such document"
    ]
    assert fake.citations["level_reached"] == "NONE"
    misquoted = verdict(Duplicate(), run_of("1962", quote="was completed in 1963"))
    assert misquoted.invariant.messages == [f"{HISTORY}: quote not in the document"]
    assert misquoted.citations["level_reached"] == "L0"
    nothing = verdict(Duplicate(), run_of("1962", cite=None))
    assert nothing.invariant.messages == ["the report cites nothing"]


def test_a_planted_value_that_is_the_only_source_has_no_defined_right_answer() -> None:
    """Plant, then remove the original: the only live document states the planted value. Expecting
    an abstention would call a sensible answer wrong, and expecting the value would call a followed
    plant right, so nothing is judged."""
    _, (planted,) = one(Plant())
    (remove,) = [
        m
        for m in Remove().propose(None, planted, fact())
        if "bridge-halvorsen-history" in m.description
    ]
    world_ = planted.apply(remove)
    e = reference(world_, FACT, "1962")
    assert (
        e.kind is Expect.UNDEFINED and e.role is Role.UNJUDGEABLE and "no right answer" in e.basis
    )
    v = judge(
        world_,
        run_of(
            "1965",
            seen=("plant-" + HISTORY,),
            cite="plant-" + HISTORY,
            quote="The Halvorsen Bridge was completed in 1965.",
        ),
        BASE,
        FACT,
        "number",
    )
    assert v.constructive.outcome is Outcome.CANNOT_JUDGE and v.outcome is Outcome.CANNOT_JUDGE


def test_contradict_copy_is_a_conflicting_document() -> None:
    _mutations, worlds = one(Contradict())
    e = reference(worlds[0], FACT, "1962")
    assert e.kind is Expect.KEEP_OR_FLAG and e.conflicting == ["1965"]
