# Proposed fixture: pending owner review (normalization and citation-check rules).
"""Normalization, citation levels and the recorded-run format."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from isitright.packs.research.documents import documents_of
from isitright.packs.research.runs import (
    Citation,
    Claim,
    RecordedRun,
    Report,
    SubjectLabel,
    check_citations,
    normalize,
    read_run,
    same_answer,
    write_run,
)

from .research_fixtures import corpus


@pytest.mark.parametrize(
    ("value", "kind", "expected"),
    [
        ("The Halvorsen Bridge!", "string", "halvorsen bridge"),
        ("  A  Bridge ", "string", "bridge"),
        ("1,962", "number", "1962"),
        ("about 12,000.50 vehicles", "number", "12000.5"),
        ("$3.00", "number", "3"),
        ("no digits", "number", None),
        ("March 3, 1962", "date", "1962-03-03"),
        ("3 March 1962", "date", "1962-03-03"),
        ("1962-03-03", "date", "1962-03-03"),
        ("completed in 1962", "date", "1962"),
        ("31 February 1962", "date", None),
        (None, "string", None),
    ],
)
def test_normalization(value, kind, expected) -> None:
    assert normalize(value, kind) == expected


def test_number_normalization_returns_text_not_a_float() -> None:
    out = normalize("1962", "number")
    assert isinstance(out, str) and not isinstance(out, float)
    assert Decimal(out) == 1962


def test_same_answer_is_three_valued() -> None:
    assert same_answer("1962", "1,962", "number") is True
    assert same_answer("1962", "1965", "number") is False
    assert same_answer("unknown", "1965", "number") is None  # cannot be read: not a mismatch


def test_an_id_is_not_a_title() -> None:
    docs = documents_of(corpus())
    report = Report(
        answer="1962",
        claims=[
            Claim(
                text="x",
                citations=[
                    Citation(doc_id="History of the Halvorsen Bridge", quote="completed in 1962")
                ],
            )
        ],
    )
    check = check_citations(report, docs)
    assert check.level == "NONE" and check.l0_failures == [
        "History of the Halvorsen Bridge: no such document"
    ]


def test_citation_levels() -> None:
    docs = documents_of(corpus())

    def level(doc_id: str, quote: str) -> str:
        report = Report(
            answer="1962",
            claims=[Claim(text="x", citations=[Citation(doc_id=doc_id, quote=quote)])],
        )
        return check_citations(report, docs).level

    assert (
        level("bridge-halvorsen-history", "The Halvorsen   Bridge was COMPLETED in 1962.") == "L1"
    )
    assert level("bridge-halvorsen-history", "was completed in 1965") == "L0"
    assert level("doc-0000", "was completed in 1962") == "NONE"
    assert (
        check_citations(Report(answer="1962", claims=[Claim(text="x")]), docs).uncited_claims == 1
    )
    assert check_citations(Report(), docs).to_json()["l2"].startswith("not judged")


def test_abstention_and_flags() -> None:
    assert Report(answer="I cannot answer this.").abstained()
    assert Report(answer=None).abstained()
    assert not Report(answer="1962").abstained()
    structured = Report(answer="1962", flags=["conflict"])
    assert structured.flagged("conflict") and structured.flag_basis() == "agent flags"
    assert not structured.flagged("retracted_source")
    keyword = Report(answer="1962 (sources disagree)")
    assert keyword.flagged("conflict") and keyword.flag_basis() == "keyword rule"
    assert Report(answer="1962", flags=[]).flagged("conflict") is False  # empty flags are an answer


def _run() -> RecordedRun:
    trace = [
        {
            "index": 0,
            "name": "search",
            "arguments": {"query": "q", "k": 2},
            "is_error": False,
            "result": json.dumps(
                {
                    "results": [
                        {"id": "a", "title": "A", "snippet": "s"},
                        {"id": "b", "title": "B", "snippet": "s"},
                    ]
                }
            ),
        },
        {"index": 1, "name": "open", "arguments": {"id": "b"}, "is_error": False, "result": "{}"},
        {
            "index": 2,
            "name": "open",
            "arguments": {"id": "zz"},
            "is_error": True,
            "result": "no document",
        },
    ]
    return RecordedRun(
        subject=SubjectLabel(kind="stand_in", name="t", written_by="Claude"),
        task_id="t",
        question="q",
        trace=trace,
        report=Report(answer="x"),
        seed=3,
    )


def test_recorded_run_derives_queries_opened_and_seen() -> None:
    run = _run()
    assert run.queries() == [{"query": "q", "k": 2, "ids": ["a", "b"]}]
    assert run.opened() == ["b"]  # the errored open is not an open
    assert run.seen() == ["a", "b"]


def test_recorded_run_round_trips_and_rejects_other_formats(tmp_path) -> None:
    path = tmp_path / "run.json"
    write_run(path, _run())
    assert read_run(path) == _run()
    path.write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read recorded run"):
        read_run(path)


def test_a_cited_document_id_is_not_a_statement_that_sources_contradict() -> None:
    """An id such as ``contradict-x`` once made the keyword rule see a conflict nobody stated."""
    cited = Citation(doc_id="contradict-bridge", quote="q")
    report = Report(
        answer="1965", claims=[Claim(text="contradict-bridge says 1965", citations=[cited])]
    )
    assert report.flagged("conflict") is False
    said = Report(answer="1965; sources contradict each other", claims=report.claims)
    assert said.flagged("conflict") is True


def test_a_citation_without_a_quote_reaches_level_zero_not_one() -> None:
    """An empty string is inside every text, so an empty quote must not count as a match."""
    docs = documents_of(corpus())
    report = Report(
        answer="1962",
        claims=[Claim(text="x", citations=[Citation(doc_id="bridge-eastgate", quote="")])],
    )
    check = check_citations(report, docs)
    assert check.level == "L0" and check.unquoted == 1 and check.l1_failures == []
    assert check.to_json()["unquoted_citations"] == 1


# ---- appended by the fixtures review ----


def test_number_normalization_reads_exact_answers_only() -> None:
    assert normalize("not 1962", "number") is None
    assert normalize("As of 2024, the answer is 1962", "number") is None
    assert normalize("it was never 1962", "number") is None
    assert normalize("1962", "number") == "1962" and normalize("about 1,962", "number") == "1962"
    assert same_answer("As of 2024, 1962", "1962", "number") is None  # not a mismatch: not judged


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("not 1962", None),
        ("not March 3, 1962", None),
        ("never completed on 1962-03-03", None),
        ("March 3, 1962 or April 4, 1963", None),
        ("1962-03-03 or 1962-03-04", None),
        ("31 February 1962", None),
        ("March 3, 1962", "1962-03-03"),
        ("completed on March 3, 1962 (March 3, 1962 per the plaque)", "1962-03-03"),
        ("1962", "1962"),
        ("completed in 1962", "1962"),
        ("March 3, 1962 or 1963", None),
        ("1962-03-03 or 1963", None),
        ("3 March 1962 (built 1958)", None),
        ("March 3, 1962, so in 1962", "1962-03-03"),
    ],
)
def test_date_answers_follow_the_same_exactness_rules_as_numbers(text, expected) -> None:
    assert normalize(text, "date") == expected


def _trace(*events):
    return RecordedRun(
        subject=SubjectLabel(kind="stand_in", name="t", written_by="Claude"),
        task_id="t",
        question="q",
        trace=[{"index": i, "is_error": False, **e} for i, e in enumerate(events)],
        report=Report(answer="x"),
    )


def _search(snippet: str, doc_id: str = "d") -> dict:
    rows = [{"id": doc_id, "title": "T", "snippet": snippet}]
    return {"name": "search", "arguments": {"query": "q"}, "result": json.dumps({"results": rows})}


def _open(text: str | None, doc_id: str = "d") -> dict:
    body = {"id": doc_id} if text is None else {"id": doc_id, "text": text}
    return {"name": "open", "arguments": {"id": doc_id}, "result": json.dumps(body)}


def test_quote_exposure_is_true_false_or_unknown_from_the_trace_alone() -> None:
    quote = "The bridge was completed in 1962."
    assert (
        _trace(_search("Intro. The bridge was completed in 1962. Later.")).quote_exposure(
            "d", quote
        )
        is True
    )
    assert _trace(_search("")).quote_exposure("d", quote) is False  # id and title only
    assert _trace(_search("The annual report mentions 1962.")).quote_exposure("d", quote) is False
    assert _trace().quote_exposure("d", quote) is False  # the document never appeared
    assert _trace(_search("The bridge was completed", "other")).quote_exposure("d", quote) is False
    assert _trace(_search("The bridge was completed")).quote_exposure("d", quote) is None  # cut
    assert (
        _trace(_open("Text. The bridge was completed in 1962. More.")).quote_exposure("d", quote)
        is True
    )
    assert _trace(_open("A different document text.")).quote_exposure("d", quote) is False
    assert _trace(_open(None)).quote_exposure("d", quote) is None  # an open result with no text
    assert _trace(_search("")).quote_exposure("d", "") is None  # no quote to look for
    errored = _trace(_open("The bridge was completed in 1962."))
    errored.trace[0]["is_error"] = True
    assert errored.quote_exposure("d", quote) is False  # a failed call showed nothing


def test_the_aggregate_exposure_is_false_if_any_quote_was_not_shown() -> None:
    from isitright.packs.research.runs import CitationCheck

    check = CitationCheck(traced=True)
    check.quote_exposure = [{"doc_id": "a", "exposed": True}, {"doc_id": "b", "exposed": None}]
    assert check.cited_quote_exposed is None
    check.quote_exposure.append({"doc_id": "c", "exposed": False})
    assert check.cited_quote_exposed is False
    check.quote_exposure = [{"doc_id": "a", "exposed": True}]
    assert check.cited_quote_exposed is True
    assert (
        CitationCheck(
            traced=False, quote_exposure=[{"doc_id": "a", "exposed": True}]
        ).cited_quote_exposed
        is None
    )
    assert CitationCheck(traced=True).cited_quote_exposed is None  # nothing cited
