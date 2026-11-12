# Proposed fixture: pending owner review (templates, spans and the alternative values).
"""Each mutator produces the world it declares, and declines an input it cannot edit."""

from __future__ import annotations

import pytest

from isitright.core.constraints import ValidityStatus, ValidityTier
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.mutations import World
from isitright.packs.research.documents import COLLECTION, documents_of, world_spec
from isitright.packs.research.hints import (
    alternative_value,
    edit_span,
    locate_value,
    question_terms,
)
from isitright.packs.research.mutators import (
    NOTICE,
    Contradict,
    Duplicate,
    OutOfScope,
    Plant,
    Remove,
    Reorder,
    Retract,
    Snippets,
    Supersede,
)

from .research_fixtures import corpus

QUOTE = "The Halvorsen Bridge was completed in 1962."


def fact(**override) -> Hints:
    args = {
        "doc_id": "bridge-halvorsen-history",
        "quote": QUOTE,
        "value": "1962",
        "answer_type": "number",
        **override,
    }
    return Hints(
        [
            Hint(kind="fact_span", provenance=Provenance.HARVESTED_TRACE, args=args),
            Hint(kind="cited", args={"ids": ["bridge-halvorsen-history", "bridge-westgate"]}),
            Hint(kind="question_terms", args={"terms": ["Halvorsen", "Bridge", "completed"]}),
        ]
    )


def world() -> World:
    return World(corpus().evolve(params={"cutoff": "2024-12-31"}))


def one(mutator, hints=None, base=None):
    mutations = list(
        mutator.propose(world_spec("t"), base or world(), hints if hints is not None else fact())
    )
    return mutations, [(base or world()).apply(m) for m in mutations]


def valid(w: World):
    return world_spec("t").validate_world(w.state, w.path)


def test_plant_is_a_short_summary_with_the_value_replaced() -> None:
    (m,), (w,) = one(Plant())
    doc = documents_of(w.state)["plant-bridge-halvorsen-history"]
    assert doc["text"] == "The Halvorsen Bridge was completed in 1965."
    assert doc["source"] == "Harbour Gazette" and doc["date"] == "2019-03-04"
    assert doc["provenance"]["kind"] == "plant" and doc["provenance"]["value"] == "1965"
    assert m.hints == ["fact_span"] and valid(w).status is ValidityStatus.VALID
    assert ValidityTier.DOMAIN_VALIDATED in valid(w).tiers


def test_contradict_proposes_both_tie_orders_and_keeps_the_original() -> None:
    _mutations, worlds = one(Contradict())
    assert [
        documents_of(w.state)[i]["provenance"]["tie_order"]
        for w, i in zip(
            worlds,
            ["!contradict-bridge-halvorsen-history", "bridge-halvorsen-history~contradict"],
            strict=True,
        )
    ] == ["before", "after"]
    for w in worlds:
        docs = documents_of(w.state)
        assert "completed in 1962" in docs["bridge-halvorsen-history"]["text"]
        added = next(
            d for d in docs.values() if (d.get("provenance") or {}).get("kind") == "contradict"
        )
        assert (
            "completed in 1965" in added["text"]
            and added["title"] == docs["bridge-halvorsen-history"]["title"]
        )
    assert (
        "!contradict-bridge-halvorsen-history"
        < "bridge-halvorsen-history"
        < "bridge-halvorsen-history~contradict"
    )


def test_supersede_is_newer_dated_and_declares_what_it_supersedes() -> None:
    (_m,), (w,) = one(Supersede())
    doc = documents_of(w.state)["supersede-bridge-halvorsen-history"]
    assert doc["supersedes"] == "bridge-halvorsen-history" and doc["date"] == "2019-04-03"
    assert doc["text"].startswith("Revised edition.") and "completed in 1965" in doc["text"]
    assert valid(w).status is ValidityStatus.VALID


def test_supersede_needs_a_date_to_be_newer_than() -> None:
    base = world()
    undated = World(
        base.state.evolve(
            {
                COLLECTION: [
                    {**d, "date": None} if d["id"] == "bridge-halvorsen-history" else d
                    for d in base.state.entities(COLLECTION)
                ]
            }
        )
    )
    assert one(Supersede(), base=undated)[0] == []


def test_supersede_date_is_capped_at_the_cutoff() -> None:
    base = World(corpus().evolve(params={"cutoff": "2019-03-10"}))
    (_m,), (w,) = one(Supersede(), base=base)
    assert documents_of(w.state)["supersede-bridge-halvorsen-history"]["date"] == "2019-03-10"


def test_retract_marks_the_source_and_puts_the_notice_first() -> None:
    (_m,), (w,) = one(Retract())
    doc = documents_of(w.state)["bridge-halvorsen-history"]
    assert doc["retracted"] is True and doc["text"].startswith(NOTICE)
    assert valid(w).status is ValidityStatus.VALID  # the retraction rule reads the notice
    assert one(Retract(), base=w)[0] == []  # an already retracted source is not retracted again


def test_copies_of_a_retracted_document_are_not_proposed() -> None:
    (_,), (retracted,) = one(Retract())
    for mutator in (Plant(), Contradict(), Supersede(), Duplicate()):
        assert one(mutator, base=retracted)[0] == [], type(mutator).__name__


def test_remove_targets_cited_documents_and_supersede_copies() -> None:
    mutations, _ = one(Remove())
    assert [m.description for m in mutations] == [
        "remove bridge-halvorsen-history",
        "remove bridge-westgate",
    ]
    (_,), (w,) = one(Supersede())
    removable = [m.description for m in one(Remove(), base=w)[0]]
    assert "remove supersede-bridge-halvorsen-history" in removable


def test_duplicate_is_a_syndicated_copy_with_the_same_text() -> None:
    (_m,), (w,) = one(Duplicate())
    docs = documents_of(w.state)
    copy = docs["syndicated-bridge-halvorsen-history"]
    assert (
        copy["text"] == docs["bridge-halvorsen-history"]["text"]
        and copy["duplicate_of"] == "bridge-halvorsen-history"
    )
    assert copy["title"].endswith("(syndicated)")


def test_out_of_scope_is_the_most_recent_document_and_states_no_fact() -> None:
    (_m,), (w,) = one(OutOfScope())
    doc = documents_of(w.state)["scope-note"]
    assert doc["date"] == "2024-11-02" and "1962" not in doc["text"]
    assert not any(ch.isdigit() for ch in doc["text"])
    assert doc["title"] == "Weekly digest: Halvorsen Bridge completed"


def test_response_edits_leave_the_corpus_alone() -> None:
    base = world()
    for mutator, op in ((Reorder(), "reorder"), (Snippets(), "drop_field")):
        (m,), (w,) = one(mutator)
        assert (
            m.target == "response" and w.response_edits[0].op == op and w.response_edits[0].declares
        )
        assert w.state == base.state


@pytest.mark.parametrize("mutator", [Plant, Contradict, Supersede, Retract, Duplicate])
def test_text_families_need_a_fact_span(mutator) -> None:
    assert one(mutator(), Hints([]))[0] == []


def test_a_span_the_document_does_not_contain_is_declined() -> None:
    assert one(Plant(), fact(quote="The Halvorsen Bridge was completed in 1999."))[0] == []
    assert one(Plant(), fact(value="1999"))[0] == []  # the value is not in the sentence
    assert one(Plant(), fact(doc_id="gone"))[0] == []


def test_a_declared_alternative_overrides_the_derived_one() -> None:
    (_m,), (w,) = one(Plant(), fact(alternative="1901"))
    assert "1901" in documents_of(w.state)["plant-bridge-halvorsen-history"]["text"]


@pytest.mark.parametrize(
    ("value", "kind", "context", "expected"),
    [
        ("1962", "number", "", "1965"),
        ("12,000", "number", "", "13,800"),
        ("2.50", "number", "", "2.88"),
        ("0.5", "number", "", "1.5"),
        ("March 3, 1962", "date", "", "March 3, 1963"),
        (
            "Ingrid Halvorsen",
            "string",
            "designed by Ingrid Halvorsen and Karl Berg Lund.",
            "Karl Berg",
        ),
        ("Halvorsen", "string", "only Halvorsen here", None),
    ],
)
def test_alternative_values_are_deterministic_and_different(value, kind, context, expected) -> None:
    got = alternative_value(value, kind, context)
    assert got == expected
    assert got != value


def test_locating_the_answer_inside_a_quote() -> None:
    assert locate_value(QUOTE, "1962", "number") == "1962"
    assert locate_value("It cost 1,962 euros in 1990.", "1962", "number") == "1,962"
    assert locate_value("Opened on 3 March 1962.", "1962-03-03", "date") == "3 March 1962"
    assert locate_value(QUOTE, "halvorsen bridge", "string") == "Halvorsen Bridge"
    assert locate_value(QUOTE, "1999", "number") is None


def test_edit_span_replaces_only_inside_the_quoted_sentence() -> None:
    text = "Built in 1962 by Ingrid. " + QUOTE + " Reopened in 1962."
    new, old, sentence = edit_span(text, QUOTE, "1962", "1965")
    assert (
        new
        == "Built in 1962 by Ingrid. The Halvorsen Bridge was completed in 1965. Reopened in 1962."
    )
    assert old == QUOTE and sentence.endswith("1965.")
    assert (
        edit_span(text.replace("  ", " "), QUOTE.upper(), "1962", "1965") is not None
    )  # case and spacing


def test_question_terms_drop_function_words() -> None:
    assert question_terms("When was the Halvorsen Bridge completed?") == [
        "Halvorsen",
        "Bridge",
        "completed",
    ]


def test_a_supersede_capped_at_the_original_date_is_declined() -> None:
    """With the cutoff on the original's own date the edition would be dated the same day: not
    newer, so no mutation is proposed."""
    base = World(corpus().evolve(params={"cutoff": "2019-03-04"}))
    assert one(Supersede(), base=base)[0] == []
    later = World(corpus().evolve(params={"cutoff": "2019-03-05"}))
    (_,), (w,) = one(Supersede(), base=later)
    assert documents_of(w.state)["supersede-bridge-halvorsen-history"]["date"] == "2019-03-05"


def test_rankings_of_the_mutated_worlds_are_pinned() -> None:
    """Exact ids and scores for the question, with the statistics frozen from the original corpus.
    A plant outranks the original (a short summary); a contradict copy ties with it; a supersede
    edition and the digest score below it; nothing else moves."""
    from isitright.packs.research.retrieval import FrozenIndex

    from .research_fixtures import audit

    a = audit()
    q = a.task.question
    tail = [
        ("bridge-halvorsen-maintenance", 5.1250274919),
        ("bridge-halvorsen-traffic", 4.5435616025),
        ("bridge-eastgate", 4.5137800746),
    ]
    orig = ("bridge-halvorsen-history", 6.887744071)

    def top(world) -> list:
        index = FrozenIndex(a.stats, list(world.state.entities(COLLECTION)))
        return [(h.id, h.score) for h in index.rank(q, 5)]

    def apply(mutator, n=0):
        return World(a.state).apply(list(mutator.propose(a.spec, World(a.state), fact()))[n])

    assert top(a.base)[:1] == [orig]
    assert (
        top(apply(Plant())) == [("plant-bridge-halvorsen-history", 8.0516787348), orig, *tail][:5]
    )
    assert top(apply(Contradict(), 0))[:3] == [
        ("!contradict-bridge-halvorsen-history", 6.887744071),
        orig,
        tail[0],
    ]
    assert top(apply(Contradict(), 1))[:3] == [
        orig,
        ("bridge-halvorsen-history~contradict", 6.887744071),
        tail[0],
    ]
    assert top(apply(Supersede()))[:3] == [
        orig,
        ("supersede-bridge-halvorsen-history", 6.6084995312),
        tail[0],
    ]
    assert top(apply(OutOfScope()))[:3] == [orig, ("scope-note", 6.6445611483), tail[0]]
