"""L2 behind a judge interface: the baseline rule's verdicts and limits, the labeling fields, and
that a judge never changes what L0 and L1 say.

Proposed fixture: pending owner review (the claims, quotes and expected verdicts are written by
Claude, who also wrote the baseline rule).
"""

from __future__ import annotations

from isitright.packs.research.runs import Citation, Claim, Report, check_citations
from isitright.packs.research.support import (
    JudgeLabel,
    Judgement,
    QuoteContainsAnswer,
    SupportVerdict,
    Validation,
    check_support,
)

DOC = {
    "id": "d1",
    "text": "The Halvorsen Bridge was completed in 1962. It was not opened to trucks until 1964.",
}
DOCS = {"d1": DOC}


def report(answer: str | None, quote: str, doc_id: str = "d1") -> Report:
    claim = Claim(text="completion year", citations=[Citation(doc_id=doc_id, quote=quote)])
    return Report(answer=answer, claims=[claim])


def verdicts(r: Report, kind: str = "number") -> list[str]:
    got = check_support(r, DOCS, QuoteContainsAnswer(), kind)  # type: ignore[arg-type]
    return [row["verdict"] for row in got.rows]


def test_the_baseline_supports_a_quote_that_states_the_answer() -> None:
    assert verdicts(report("1962", "The Halvorsen Bridge was completed in 1962.")) == ["SUPPORTED"]


def test_the_baseline_never_says_not_supported() -> None:
    """A quote without the value may support the claim in other words: only CANNOT_JUDGE."""
    other = "It was not opened to trucks until 1964."
    assert verdicts(report("1962", other)) == ["CANNOT_JUDGE"]
    assert verdicts(report("1962", "Halvorsen Bridge was completed")) == ["CANNOT_JUDGE"]
    assert SupportVerdict.NOT_SUPPORTED.value not in verdicts(report("1999", other))


def test_a_negation_cue_in_the_quote_withholds_support() -> None:
    doc = {"id": "d1", "text": "It was not completed in 1962 as planned."}
    got = check_support(
        report("1962", "It was not completed in 1962 as planned."),
        {"d1": doc},
        QuoteContainsAnswer(),
        "number",
    )
    assert got.rows[0]["verdict"] == "CANNOT_JUDGE" and "negation" in got.rows[0]["basis"]


def test_no_answer_or_a_free_text_answer_cannot_be_judged() -> None:
    assert verdicts(report(None, "completed in 1962")) == ["CANNOT_JUDGE"]
    assert verdicts(report("the bridge opened in the early sixties", "completed in 1962")) == [
        "CANNOT_JUDGE"
    ]


def test_a_number_inside_another_number_is_not_the_answer() -> None:
    doc = {"id": "d1", "text": "The span is 19620 metres long."}
    got = check_support(
        report("1962", "The span is 19620 metres long."),
        {"d1": doc},
        QuoteContainsAnswer(),
        "number",
    )
    assert got.rows[0]["verdict"] == "CANNOT_JUDGE"


def test_citations_that_did_not_reach_l1_are_not_sent_to_the_judge() -> None:
    called: list[str] = []

    class Spy:
        label = JudgeLabel("spy", "rule", "records calls")

        def judge(self, *args: object) -> Judgement:
            called.append("called")
            return Judgement(SupportVerdict.SUPPORTED, "spy")

    r = Report(
        answer="1962",
        claims=[
            Claim(
                text="a",
                citations=[
                    Citation(doc_id="missing", quote="completed in 1962"),  # L0 fails
                    Citation(doc_id="d1", quote="completed in 1990"),  # L1 fails
                    Citation(doc_id="d1", quote=""),  # unquoted
                    Citation(doc_id="d1", quote="completed in 1962"),  # reaches L1
                ],
            )
        ],
    )
    got = check_support(r, DOCS, Spy(), "number")
    assert (got.skipped, got.supported, called) == (3, 1, ["called"])


def test_the_result_names_the_judge_and_whether_it_was_validated() -> None:
    got = check_support(
        report("1962", "completed in 1962"), DOCS, QuoteContainsAnswer(), "number"
    ).to_json()
    assert got["judge"]["kind"] == "deterministic_baseline" and got["judge"]["validated"] is False
    assert got["supported"] == 1 and got["citations_judged"] == 1
    assert "changes neither the level nor any outcome" in got["level"]
    model = JudgeLabel(
        "m",
        "model",
        "a model judge",
        Validation(labeled=40, agree=36, false_supported=2, false_not_supported=2, source="owner"),
        "model-x prompt-v3",
    ).to_json()
    assert model["validated"] is True and model["validation"]["false_supported"] == 2
    assert model["version"] == "model-x prompt-v3"


def test_a_judge_leaves_l0_and_l1_alone() -> None:
    r = report("1962", "The Halvorsen Bridge was completed in 1962.")
    before = (
        check_citations(r, DOCS).summary() if hasattr(check_citations(r, DOCS), "summary") else None
    )
    check_support(r, DOCS, QuoteContainsAnswer(), "number")
    after = (
        check_citations(r, DOCS).summary() if hasattr(check_citations(r, DOCS), "summary") else None
    )
    assert before == after
    assert check_citations(r, DOCS).l0_failures == [] == check_citations(r, DOCS).l1_failures
