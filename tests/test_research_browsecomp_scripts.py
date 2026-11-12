# Proposed fixture: pending owner review (synthetic data; no BrowseComp-Plus text is used here).
"""The BrowseComp-Plus demo scripts: decoding, the recorded run built from a published run, and the
fact span taken from the baseline trace. Synthetic data only: the benchmark asks that its data not
appear as plain text online, so none is committed."""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "examples" / "research" / "browsecomp_plus")
)

import audit_demo
import common

from isitright.core.hints import Provenance
from isitright.packs.research.agents import ResearchTask
from isitright.packs.research.runs import Report


def encrypt(text: str) -> str:
    raw = text.encode()
    key = hashlib.sha256(common.CANARY.encode()).digest()
    key = (key * (len(raw) // len(key) + 1))[: len(raw)]
    return base64.b64encode(bytes(a ^ b for a, b in zip(raw, key, strict=True))).decode()


def test_decrypt_round_trips_and_the_key_depends_on_the_canary() -> None:
    assert common.decrypt(encrypt("Queen Arwa University")) == "Queen Arwa University"
    assert common.decrypt(encrypt("a" * 200)) == "a" * 200  # the key is repeated past 32 bytes
    wrong = base64.b64encode(bytes(b ^ 1 for b in base64.b64decode(encrypt("abc")))).decode()
    assert common.decrypt(wrong) != "abc"


def test_final_message_is_split_into_explanation_and_exact_answer() -> None:
    text = "Explanation: built in 1962 [12][34].\n\nExact Answer: Halvorsen Bridge\nConfidence: 90%"
    explanation, answer = common.parse_final(text)
    assert answer == "Halvorsen Bridge" and explanation.endswith("[12][34].")
    assert common.parse_final("no answer line")[1] is None
    assert common.normalize_answer("The Halvorsen Bridge!") == "halvorsen bridge"


def test_decode_run_reads_searches_and_the_final_message() -> None:
    hits = '[{"docid": "7", "score": 3.5, "snippet": "s"}]'
    run = {
        "query_id": "9",
        "status": "completed",
        "result": [
            {"type": "reasoning", "tool_name": None, "arguments": None, "output": []},
            {
                "type": "tool_call",
                "tool_name": "search",
                "arguments": '{"query": "q1"}',
                "output": encrypt(hits),
            },
            {
                "type": "output_text",
                "tool_name": None,
                "arguments": None,
                "output": encrypt("Exact Answer: X"),
            },
        ],
    }
    decoded = common.decode_run(run)
    assert decoded["searches"] == [
        {"query": "q1", "hits": [{"docid": "7", "score": 3.5, "snippet": "s"}]}
    ]
    assert decoded["final"] == "Exact Answer: X" and decoded["status"] == "completed"


DOCS = {
    "7": {
        "id": "7",
        "title": "Bridge facts",
        "source": "example.org",
        "date": "2019-03-04",
        "text": "---\ntitle: Bridge facts\ndate: 2019-03-04\n---\nIntro. The Halvorsen Bridge was "
        "completed in 1962 by Ingrid Halvorsen. More text.",
    }
}


def test_front_matter_and_dates() -> None:
    meta = audit_demo.front_matter(DOCS["7"]["text"])
    assert meta == {"title": "Bridge facts", "date": "2019-03-04"}
    assert (
        audit_demo.iso_date("2015-05-01T00:00") == "2015-05-01"
        and audit_demo.iso_date("May") is None
    )
    assert audit_demo.iso_date(None) is None


def decoded() -> dict:
    return {
        "searches": [
            {
                "query": "Halvorsen bridge",
                "hits": [{"docid": "7", "score": 1.0, "snippet": "x" * 300}],
            }
        ],
        "final": "Explanation: opened in 1962 [7], old [99].\n\nExact Answer: Ingrid Halvorsen",
    }


def task() -> ResearchTask:
    return ResearchTask(
        id="bcp-9",
        question="Who designed it?",
        gold="Ingrid Halvorsen",
        gold_basis=audit_demo.GOLD_BASIS,
    )


def test_the_recorded_run_cites_by_id_without_quotes_and_only_ids_in_the_world() -> None:
    run = audit_demo.recorded_run(decoded(), DOCS, task())
    assert (
        run.subject.kind == "recorded"
        and "published by the BrowseComp-Plus authors" in run.subject.written_by
    )
    assert run.report.answer == "Ingrid Halvorsen"
    citations = [c for claim in run.report.claims for c in claim.citations]
    assert [(c.doc_id, c.quote) for c in citations] == [("7", "")]  # 99 is not in the world
    assert run.queries() == [{"query": "Halvorsen bridge", "k": 5, "ids": ["7"]}]
    assert len(__import__("json").loads(run.trace[0]["result"])["results"][0]["snippet"]) == 240


def test_the_fact_span_comes_from_the_agents_answer_not_the_gold() -> None:
    report = Report(
        answer="Ingrid Halvorsen",
        claims=[audit_demo.Claim(text="c", citations=[audit_demo.Citation(doc_id="7", quote="")])],
    )
    hint = audit_demo.fact_span_hint(report, DOCS)
    assert hint is not None and hint.provenance is Provenance.HARVESTED_TRACE
    assert hint.args["value"] == "Ingrid Halvorsen" and hint.args["doc_id"] == "7"
    assert hint.args["quote"] in DOCS["7"]["text"] and "Ingrid Halvorsen" in hint.args["quote"]
    assert audit_demo.fact_span_hint(Report(answer="Nobody", claims=report.claims), DOCS) is None
    assert audit_demo.fact_span_hint(Report(answer=None), DOCS) is None


def test_a_long_sentence_gives_a_window_that_is_still_inside_the_text() -> None:
    text = "start. " + "word " * 200 + "Target value here " + "word " * 200 + "end."
    start = text.index("Target value")
    quote = audit_demo.sentence_around(text, start, start + len("Target value"))
    assert quote in text and "Target value" in quote and len(quote) <= 400


def test_a_fact_span_in_a_negation_or_front_matter_is_not_accepted() -> None:
    """The first sentence that contains the answer may deny it, or sit in the front matter."""
    answer = "Ingrid Halvorsen"
    claims = [audit_demo.Claim(text="c", citations=[audit_demo.Citation(doc_id="n", quote="")])]
    report = Report(answer=answer, claims=claims)

    def doc(text: str) -> dict:
        return {"n": {"id": "n", "title": "t", "text": text}}

    denied = doc(
        "Earlier reports incorrectly credited Ingrid Halvorsen with the design. Other text."
    )
    assert audit_demo.fact_span_hint(report, denied) is None
    front = doc("---\ntitle: Ingrid Halvorsen\ndate: 2019-01-01\n---\nBody without the name.")
    assert audit_demo.fact_span_hint(report, front) is None
    # a later body sentence is still found when the first match is rejected
    mixed = doc(
        "The claim that Ingrid Halvorsen did not design it is disputed. "
        "Ingrid Halvorsen designed it."
    )
    hint = audit_demo.fact_span_hint(report, mixed)
    assert hint is not None and hint.args["quote"] == "Ingrid Halvorsen designed it."
    assert hint.args["confidence"].startswith("heuristic")


def test_span_rejection_names_the_reason() -> None:
    text = "---\ntitle: X\n---\nHe never built it. She built it."
    assert audit_demo.span_rejection(text, 4, "---") == "the answer occurs in the front matter"
    assert "negation" in audit_demo.span_rejection(text, 20, "He never built it.")
    assert audit_demo.span_rejection(text, 40, "She built it.") is None
