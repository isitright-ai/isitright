"""L2, "the cited document supports the claim", behind a judge interface (0.9).

0.8 reports L0 (the cited id exists) and L1 (the quote occurs in the document) and says L2 is not
judged. L2 needs a judgment of meaning. This module defines what such a judge is and what it must
state about itself, ships one deterministic baseline whose limits are plain, and runs a judge over
a report. **No model judge is run or shipped**: a judge you write may call a model, and then its
verdicts are labeled with it (``JudgeLabel.kind == "model"``) and are not evidence until validated.

Nothing here changes the citation level or any oracle outcome; L2 results are reported beside L0
and L1. Offline, with no judge given, L2 stays ``CANNOT_JUDGE`` as in 0.8.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from isitright.core.world import Entity
from isitright.packs.research.runs import AnswerKind, Report, normalize, squash


class SupportVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    CANNOT_JUDGE = "CANNOT_JUDGE"


@dataclass(frozen=True)
class Validation:
    """How a judge was checked against human labels. Without it a judge's verdicts are unvalidated,
    and the report says so. The counts are of a labeled set the judge was run on; no rate is
    derived from a small set."""

    labeled: int
    agree: int
    false_supported: int
    """Human: not supported; judge: supported. The costly error for an audit."""
    false_not_supported: int
    source: str = ""
    """Where the labels came from and who made them."""


@dataclass(frozen=True)
class JudgeLabel:
    name: str
    kind: Literal["deterministic_baseline", "rule", "model", "human"]
    description: str
    validation: Validation | None = None
    version: str = ""
    """For a model judge: the model and the prompt's version; part of what is being trusted."""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "version": self.version,
            "validated": self.validation is not None,
            "validation": None
            if self.validation is None
            else {
                "labeled": self.validation.labeled,
                "agree": self.validation.agree,
                "false_supported": self.validation.false_supported,
                "false_not_supported": self.validation.false_not_supported,
                "source": self.validation.source,
            },
        }


@dataclass(frozen=True)
class Judgement:
    verdict: SupportVerdict
    basis: str


class SupportJudge(Protocol):
    """Decides whether ``document_text`` supports ``claim`` as cited with ``quote``.

    Called only for a citation that reached L1 (its quote occurs in the document). ``answer`` is
    the report's answer and ``kind`` its type. Return ``CANNOT_JUDGE`` for anything the judge is
    not sure of: an uncertain verdict must never be ``SUPPORTED``.
    """

    label: JudgeLabel

    def judge(
        self, claim: str, quote: str, document_text: str, answer: str | None, kind: AnswerKind
    ) -> Judgement: ...


_NEGATION = re.compile(
    r"\b(not|no|never|neither|nor|isn't|wasn't|didn't|n't|retracted|withdrawn|incorrect|error)\b",
    re.IGNORECASE,
)


class QuoteContainsAnswer:
    """Baseline: the claim is supported if the report's own answer, normalized as its type says,
    occurs inside the cited quote and the quote carries no negation or retraction cue.

    Where it is justified: for a closed-form answer (a number, a date, a short string) a quote that
    states exactly that value, with no word that turns it around, is what "the document says so"
    means to a person reading the citation. Where it is not: it cannot tell a quote that states the
    value as a fact from one that states it as a hypothesis, a past plan or a different subject, and
    it does not read the claim. So it only ever says ``SUPPORTED`` (when both conditions hold) or
    ``CANNOT_JUDGE``; it never says ``NOT_SUPPORTED``, because a quote without the value may
    support the claim in other words. It is a rule, not a model, and it is not validated.
    """

    label = JudgeLabel(
        name="quote-contains-answer",
        kind="deterministic_baseline",
        description=(
            "supported when the normalized answer occurs in the cited quote and the quote has no "
            "negation or retraction cue; otherwise cannot judge. Never says not supported."
        ),
    )

    def judge(
        self, claim: str, quote: str, document_text: str, answer: str | None, kind: AnswerKind
    ) -> Judgement:
        if answer is None or not answer.strip():
            return Judgement(SupportVerdict.CANNOT_JUDGE, "the report gives no answer to look for")
        wanted = normalize(answer, kind)
        if wanted is None:
            return Judgement(
                SupportVerdict.CANNOT_JUDGE, "the answer is not closed-form: nothing to look for"
            )
        if squash(quote) not in squash(document_text):
            return Judgement(SupportVerdict.CANNOT_JUDGE, "the quote is not in the document (L1)")
        if _NEGATION.search(quote):
            return Judgement(
                SupportVerdict.CANNOT_JUDGE, "the quote has a negation or retraction cue"
            )
        if normalize(quote, kind) == wanted or _contains(quote, wanted):
            return Judgement(SupportVerdict.SUPPORTED, f"the quote states {wanted!r}")
        return Judgement(
            SupportVerdict.CANNOT_JUDGE,
            f"the quote does not contain {wanted!r}; it may still support the claim in other words",
        )


def _contains(quote: str, wanted: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(wanted)}(?![\w])", squash(quote)) is not None


@dataclass
class SupportResult:
    judge: JudgeLabel
    supported: int = 0
    not_supported: int = 0
    cannot_judge: int = 0
    skipped: int = 0
    """Citations not sent to the judge: no document, no quote, or a quote not in the document."""
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        total = self.supported + self.not_supported + self.cannot_judge
        return {
            "judge": self.judge.to_json(),
            "citations_judged": total,
            "supported": self.supported,
            "not_supported": self.not_supported,
            "cannot_judge": self.cannot_judge,
            "skipped_before_l2": self.skipped,
            "level": "L2 reported beside L0 and L1; it changes neither the level nor any outcome",
            "rows": self.rows,
        }


def check_support(
    report: Report,
    documents: Mapping[str, Entity],
    judge: SupportJudge,
    kind: AnswerKind,
) -> SupportResult:
    """Run ``judge`` on every citation of ``report`` that reached L1."""
    result = SupportResult(judge.label)
    for claim in report.claims:
        for citation in claim.citations:
            doc = documents.get(citation.doc_id)
            if doc is None or not citation.quote.strip():
                result.skipped += 1
                continue
            text = str(doc["text"])
            if squash(citation.quote) not in squash(text):
                result.skipped += 1
                continue
            try:
                got = judge.judge(claim.text, citation.quote, text, report.answer, kind)
                if not isinstance(got, Judgement) or not isinstance(got.verdict, SupportVerdict):
                    raise TypeError(f"the judge returned {type(got).__name__}, not a Judgement")
            except Exception as error:  # a judge that fails has not judged: never "supported"
                got = Judgement(
                    SupportVerdict.CANNOT_JUDGE,
                    f"the judge failed: {type(error).__name__}: {str(error)[:200]}",
                )
            if got.verdict is SupportVerdict.SUPPORTED:
                result.supported += 1
            elif got.verdict is SupportVerdict.NOT_SUPPORTED:
                result.not_supported += 1
            else:
                result.cannot_judge += 1
            result.rows.append(
                {"doc_id": citation.doc_id, "verdict": got.verdict.value, "basis": got.basis}
            )
    return result
