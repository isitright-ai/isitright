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
