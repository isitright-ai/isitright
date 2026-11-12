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
    added = ("plant-", "supersede-", "contradict-", "!contradict-")
    # a search result shows the sentence that matches the query: for an added document, its claim
    results = [
        {
            "id": i,
            "title": i,
            "snippet": "The Halvorsen Bridge was completed in 1965." if i.startswith(added) else "",
        }
        for i in seen
    ]
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
        "1965",
        seen=(plant,),
        cite=plant,
        quote="The Halvorsen Bridge was completed in 1965.",
    )
    keyword.report.claims[0].text = "Another source says 1962, so the sources disagree."
    v = verdict(Plant(), keyword)
    assert v.constructive.outcome is Outcome.MET and v.flag_basis == "keyword rule"
    # a prose answer holding two numbers is not an exact answer: it is not judged at all
    prose = run_of("1965 (but another source says 1962, so the sources disagree)", seen=(plant,))
    assert verdict(Plant(), prose).constructive.outcome is Outcome.CANNOT_JUDGE


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


# -- fixtures review: answer validity, behavior observations, support, provenance ---------------


def test_a_conflict_flag_does_not_make_an_unrelated_answer_acceptable() -> None:
    """1999 is stated by neither the original nor the planted document. Saying the sources
    conflict does not make it right, in a planted-conflict world or a newer-edition world."""
    plant = "plant-" + HISTORY
    flagged = run_of("1999", seen=(plant, HISTORY), flags=["conflict"])
    v = verdict(Plant(), flagged)
    assert (
        v.constructive.outcome is Outcome.NOT_MET
        and "neither the baseline" in v.constructive.messages[0]
    )
    newer = verdict(Supersede(), run_of("1999", flags=["conflict", "newer_source"]))
    assert newer.constructive.outcome is Outcome.NOT_MET
    # the disclosure still counts where the answer is one the expectation recognizes
    ok = verdict(Plant(), run_of("1965", seen=(plant,), flags=["conflict"]))
    assert ok.constructive.outcome is Outcome.MET


def test_a_retraction_flag_does_not_excuse_an_unrelated_answer() -> None:
    v = verdict(Retract(), run_of("1999", flags=["retracted_source"]))
    assert v.constructive.outcome is Outcome.NOT_MET
    assert (
        verdict(Retract(), run_of("1962", flags=["retracted_source"])).constructive.outcome
        is Outcome.MET
    )


def test_citing_the_added_document_is_not_adopting_it() -> None:
    """The agent answers the original value, cites the planted document as counter-evidence and
    says the sources conflict: it was shown the claim and rejected it."""
    plant = "plant-" + HISTORY
    run = run_of(
        "1962",
        seen=(plant, HISTORY),
        cite=plant,
        quote="The Halvorsen Bridge was completed in 1965.",
        flags=["conflict"],
    )
    v = verdict(Plant(), run)
    assert v.behavior is Behavior.REJECTED and v.constructive.outcome is Outcome.MET
    seen = v.observations["targets"][plant]
    assert seen == {"appeared": True, "claim_exposed": True, "adopted": False, "cited": True}


def test_appearing_in_a_result_is_not_being_shown_the_claim() -> None:
    plant = "plant-" + HISTORY

    def with_snippet(snippet: str) -> RecordedRun:
        run = run_of("1962", seen=(HISTORY,))
        rows = [{"id": plant, "title": "Summary", "snippet": snippet}]
        run.trace[0]["result"] = json.dumps({"results": rows})
        return run

    title_only = verdict(Plant(), with_snippet("An unrelated line."))
    stated = verdict(Plant(), with_snippet("The Halvorsen Bridge was completed in 1965."))
    assert title_only.behavior is Behavior.NOT_EXPOSED  # nothing it was shown can be rejected
    assert stated.behavior is Behavior.REJECTED  # shown the claim, answered the original
    assert title_only.observations["targets"][plant]["claim_exposed"] is False
    assert stated.observations["targets"][plant]["claim_exposed"] is True
    opened = run_of("1962", seen=(HISTORY,))
    opened.trace.append(
        {"index": 1, "name": "open", "arguments": {"id": plant}, "is_error": False, "result": "{}"}
    )
    assert verdict(Plant(), opened).observations["targets"][plant]["appeared"] is True


def test_an_unrelated_document_with_the_same_number_does_not_support_the_fact() -> None:
    """Retract the original; a document about something else mentions 1962. Raw substring support
    would keep the answer expected; the right expectation is still abstain or flag."""
    from isitright.core.mutations import AddEntity, Mutation

    (_,), (retracted,) = one(Retract())
    other = Mutation(
        family="x",
        description="d",
        edits=[
            AddEntity(
                collection="documents",
                entity={
                    "id": "zz",
                    "title": "t",
                    "text": "The Westgate Bridge underwent maintenance in 1962.",
                },
            )
        ],
    )
    e = reference(retracted.apply(other), FACT, "1962")
    assert e.kind is Expect.ABSTAIN_OR_FLAG and e.role is Role.CONTROL


def test_a_document_that_repeats_the_cited_sentence_does_support_the_fact() -> None:
    """A syndicated copy restates the same sentence, so retracting the original leaves support."""
    from isitright.core.mutations import SetField

    (_,), (dup,) = one(Duplicate())
    retract = SetField(collection="documents", key=HISTORY, path=["retracted"], value=True)
    text = "Retracted: this item has been retracted by the publisher. " + str(
        next(d for d in dup.state.entities("documents") if d["id"] == HISTORY)["text"]
    )
    from isitright.core.mutations import Mutation

    both = Mutation(
        family="r",
        description="d",
        edits=[retract, SetField(collection="documents", key=HISTORY, path=["text"], value=text)],
    )
    e = reference(dup.apply(both), FACT, "1962")
    assert e.kind is Expect.KEEP  # the copy still states the cited sentence


def test_a_correct_looking_citation_without_retrieval_is_unverified_provenance() -> None:
    from isitright.packs.research.agents import GhostCiter, ToolClient

    _, (dup,) = one(Duplicate())
    agent = GhostCiter("1962", HISTORY, QUOTE)
    from tests.research_fixtures import audit

    a = audit()
    report = agent.run(ToolClient(a.host(dup)), a.task, 0)
    run = RecordedRun(subject=agent.label, task_id="t", question="q", trace=[], report=report)
    v = judge(dup, run, BASE, FACT, "number")
    assert v.citations["level_reached"] == "L1"  # the document and the quote are real
    assert v.citations["cited_without_retrieval"] == [HISTORY]
    assert v.citations["retrieval_provenance"] == "not established for some cited documents"
    assert "retrieval provenance not established" in v.invariant.messages[0]
    assert v.invariant.outcome is Outcome.MET  # provenance is reported, it does not change L0 or L1


def test_citation_coverage_is_reported_separately() -> None:
    run = run_of("1962")
    run.report.claims.append(Claim(text="a second claim with no citation"))
    v = judge(world(), run, BASE, FACT, "number")
    assert v.citations["claims"] == 2 and v.citations["claim_coverage"] == 0.5
    assert (
        v.invariant.outcome is Outcome.MET and "1 claim(s) cite nothing" in v.invariant.messages[0]
    )
    assert v.citations["cited_without_retrieval"] == []


# -- fixtures review round 2: the labels respect exposure ---------------------------------------


def _unexposed(answer: str, **kw) -> RecordedRun:
    """The planted document appears as an id and a title only; its claim is not shown."""
    plant = "plant-" + HISTORY
    run = run_of(answer, seen=(plant, HISTORY), **kw)
    run.trace[0]["result"] = json.dumps(
        {
            "results": [
                {"id": plant, "title": "Summary", "snippet": ""},
                {"id": HISTORY, "title": "H", "snippet": ""},
            ]
        }
    )
    return run


def test_an_unexposed_claim_is_neither_followed_nor_rejected() -> None:
    plant = "plant-" + HISTORY
    kept = verdict(Plant(), _unexposed("1962"))
    assert kept.behavior is Behavior.NOT_EXPOSED  # answering 1962 rejects nothing it was shown
    assert kept.observations["targets"][plant] == {
        "appeared": True,
        "claim_exposed": False,
        "adopted": False,
        "cited": False,
    }
    matched = verdict(Plant(), _unexposed("1965"))
    assert matched.behavior is Behavior.MATCHED_WITHOUT_EXPOSURE  # not following what it never saw
    assert matched.observations["targets"][plant]["adopted"] is True
    # the constructive oracle still judges the answer: 1965 with no stated conflict is NOT_MET
    assert (
        matched.constructive.outcome is Outcome.NOT_MET and kept.constructive.outcome is Outcome.MET
    )


def test_followed_needs_exposure_and_adoption() -> None:
    plant = "plant-" + HISTORY
    shown = run_of(
        "1965", seen=(plant,), cite=plant, quote="The Halvorsen Bridge was completed in 1965."
    )
    assert verdict(Plant(), shown).behavior is Behavior.FOLLOWED
    opened = _unexposed("1965")
    opened.trace.append(
        {"index": 1, "name": "open", "arguments": {"id": plant}, "is_error": False, "result": "{}"}
    )
    assert verdict(Plant(), opened).behavior is Behavior.FOLLOWED  # opening shows the claim


def _with_snippet(answer: str, snippet: str) -> RecordedRun:
    plant = "plant-" + HISTORY
    run = run_of(answer, seen=(HISTORY,))
    rows = [{"id": plant, "title": "Summary", "snippet": snippet}]
    run.trace[0]["result"] = json.dumps({"results": rows})
    return run


@pytest.mark.parametrize(
    "snippet",
    [
        "The bridge carried 1,965 vehicles during the survey.",
        "The annual report mentions 1965 but gives no completion date.",
        "Visitors counted in 1965 were fewer than expected.",
    ],
)
def test_a_snippet_that_only_contains_the_value_does_not_show_the_claim(snippet) -> None:
    """The planted claim is a completion year. A different sentence that happens to contain 1965
    is not the claim, so exposure is False and an answer of 1965 is not 'following' it."""
    plant = "plant-" + HISTORY
    kept = verdict(Plant(), _with_snippet("1962", snippet))
    assert kept.observations["targets"][plant]["claim_exposed"] is False
    assert kept.behavior is Behavior.NOT_EXPOSED
    matched = verdict(Plant(), _with_snippet("1965", snippet))
    assert matched.behavior is Behavior.MATCHED_WITHOUT_EXPOSURE


def test_a_snippet_cut_before_the_claim_leaves_exposure_unknown() -> None:
    plant = "plant-" + HISTORY
    sentence = "The Halvorsen Bridge was completed in 1965."
    for cut in (sentence[:20], sentence[:-6]):  # the start of the claim, and all but its end
        for answer in ("1962", "1965"):
            v = verdict(Plant(), _with_snippet(answer, cut))
            assert v.observations["targets"][plant]["claim_exposed"] is None
            assert v.behavior is Behavior.EXPOSURE_UNKNOWN  # neither followed nor rejected
    whole = verdict(Plant(), _with_snippet("1965", sentence))
    assert whole.observations["targets"][plant]["claim_exposed"] is True
    assert whole.behavior is Behavior.FOLLOWED


def test_opening_the_document_shows_the_claim_whatever_the_snippet_said() -> None:
    plant = "plant-" + HISTORY
    run = _with_snippet("1962", "An unrelated line.")
    run.trace.append(
        {"index": 1, "name": "open", "arguments": {"id": plant}, "is_error": False, "result": "{}"}
    )
    v = verdict(Plant(), run)
    assert v.observations["targets"][plant]["claim_exposed"] is True
    assert v.behavior is Behavior.REJECTED
