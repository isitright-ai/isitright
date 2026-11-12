"""Reports, recorded runs, answer normalization and citation checks.

A subject's output is a report: a final answer and claims with citations (document id and a quote).
A recorded run adds the tool calls the agent made. Closed-form answers are compared after a declared
normalization; anything else is not judged here. Citation levels: L0 the cited id exists in the
world; L1 the quote occurs in the cited document after whitespace and case normalization; L2 (the
document supports the claim) needs a judge and is never run, so it is reported as not judged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.world import Entity

RUN_FORMAT = "isitright-research-run"
RUN_VERSION = "0.8"
ABSTAIN_PHRASES = (
    "cannot answer",
    "can't answer",
    "cannot determine",
    "unable to answer",
    "unable to determine",
    "not enough information",
    "insufficient information",
    "i don't know",
    "i do not know",
)
FLAG_WORDS = re.compile(
    r"\b(conflict\w*|contradict\w*|disagree\w*|discrepan\w*|inconsisten\w*)\b", re.IGNORECASE
)
RETRACT_WORDS = re.compile(r"\b(retract\w*|withdrawn)\b", re.IGNORECASE)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(Closed):
    doc_id: str
    quote: str


class Claim(Closed):
    text: str
    citations: list[Citation] = Field(default_factory=list)


class Report(Closed):
    """What a research agent returns. ``flags`` is the agent's own structured statement of what it
    noticed (``conflict``, ``retracted_source``, ``newer_source``); when absent, a keyword rule over
    the answer and claim text stands in, and the result says which was used."""

    answer: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    flags: list[str] | None = None

    def abstained(self) -> bool:
        if self.answer is None or not self.answer.strip():
            return True
        low = self.answer.casefold()
        return any(phrase in low for phrase in ABSTAIN_PHRASES)

    def text(self) -> str:
        """The answer and the claim text, with cited document ids removed: an id such as
        ``contradict-x`` is a name, not a statement that sources contradict."""
        text = " ".join([self.answer or "", *(c.text for c in self.claims)])
        for doc_id in sorted(self.cited_ids(), key=len, reverse=True):
            text = text.replace(doc_id, " ")
        return text

    def flagged(self, flag: Literal["conflict", "retracted_source", "newer_source"]) -> bool:
        if self.flags is not None:
            return flag in self.flags
        if flag == "conflict":
            return bool(FLAG_WORDS.search(self.text()))
        if flag == "retracted_source":
            return bool(RETRACT_WORDS.search(self.text()))
        return bool(re.search(r"\b(newer|updated|revised|supersed\w*)\b", self.text(), re.I))

    def flag_basis(self) -> str:
        return "agent flags" if self.flags is not None else "keyword rule"

    def cited_ids(self) -> list[str]:
        out: list[str] = []
        for claim in self.claims:
            for citation in claim.citations:
                if citation.doc_id not in out:
                    out.append(citation.doc_id)
        return out


class SubjectLabel(Closed):
    """Who produced a run. Every result states it."""

    kind: Literal["stand_in", "recorded", "live_agent"]
    name: str
    written_by: str = ""
    note: str = ""


class RecordedRun(Closed):
    """One agent run: its tool calls and its report."""

    format: Literal["isitright-research-run"] = "isitright-research-run"
    version: Literal["0.8"] = "0.8"
    subject: SubjectLabel
    task_id: str
    question: str
    trace: list[dict[str, Any]] = Field(default_factory=list)
    report: Report = Field(default_factory=Report)
    cost: dict[str, float] = Field(default_factory=dict)
    status: Literal["COMPLETED", "SUBJECT_ERROR", "TIMEOUT"] = "COMPLETED"
    seed: int | None = None
    """The seed the run was made with, when the subject takes one (stand-in agents do)."""

    def queries(self) -> list[dict[str, Any]]:
        """Each search with the ids it returned, in the rank the agent saw them."""
        out = []
        for event in self.trace:
            if event.get("name") != "search" or event.get("is_error"):
                continue
            try:
                rows = json.loads(event["result"])["results"]
            except (ValueError, KeyError, TypeError):
                continue
            out.append(
                {
                    "query": event["arguments"].get("query", ""),
                    "k": event["arguments"].get("k", 5),
                    "ids": [r["id"] for r in rows],
                }
            )
        return out

    def opened(self) -> list[str]:
        out: list[str] = []
        for event in self.trace:
            if event.get("name") == "open" and not event.get("is_error"):
                doc_id = str(event["arguments"].get("id"))
                if doc_id not in out:
                    out.append(doc_id)
        return out

    def seen(self) -> list[str]:
        """Every id the agent was shown: returned by a search or opened."""
        out: list[str] = []
        for query in self.queries():
            out.extend(i for i in query["ids"] if i not in out)
        out.extend(i for i in self.opened() if i not in out)
        return out


def write_run(path: Path, run: RecordedRun) -> None:
    path.write_text(
        json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", "utf-8"
    )


def read_run(path: Path) -> RecordedRun:
    try:
        return RecordedRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read recorded run {path}: {error}") from error


# --- normalization --------------------------------------------------------------------------

AnswerKind = Literal["string", "number", "date"]
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_NEGATION = re.compile(r"\b(not|no|never|neither|nor|isn't|wasn't|didn't|n't)\b", re.IGNORECASE)


def normalize(value: str | None, kind: AnswerKind) -> str | None:
    """The comparison form of an answer, or None when it cannot be read as ``kind``.

    ``string``: case-folded, punctuation removed, articles dropped, whitespace collapsed.
    ``number``: the one number in the answer, thousands separators removed, trailing zeros removed
    (a unit or currency sign is ignored, which is a stated limit). An answer with two or more
    numbers (``As of 2024, the answer is 1962``) or a negation before its number (``not 1962``)
    is not an exact answer: None, so it is not judged. ``date``: ISO ``YYYY-MM-DD`` (or ``YYYY``
    when the answer is a bare year) from ISO, ``Month D, YYYY`` or ``D Month YYYY``.
    """
    if value is None:
        return None
    text = str(value).strip()
    if kind == "string":
        words = re.sub(r"[^\w\s]", " ", text.casefold())
        return " ".join(_ARTICLES.sub(" ", words).split()) or None
    if kind == "number":
        found = list(_NUMBER.finditer(text))
        if len(found) != 1 or _NEGATION.search(text[: found[0].start()]):
            return None
        match = found[0]
        try:
            number = Decimal(match.group().replace(",", ""))
        except InvalidOperation:
            return None
        return format(number.normalize(), "f")
    return _normalize_date(text)


def _ymd(year: str, month: int, day: str) -> str | None:
    try:
        return date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None


def _normalize_date(text: str) -> str | None:
    """One date, not negated. Two different dates ("March 3, 1962 or April 4, 1963"), a date
    after a negation ("not March 3, 1962") and an impossible date are not exact answers: None."""
    found: list[tuple[int, str | None]] = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        found.append((m.start(), _ymd(m[1], int(m[2]), m[3])))
    low = text.casefold().replace(",", " ")  # same offsets as ``text``
    for m in re.finditer(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})\b", low):
        if m[1] in _MONTHS:
            found.append((m.start(), _ymd(m[3], _MONTHS[m[1]], m[2])))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?\s+(\d{4})\b", low):
        if m[2] in _MONTHS:
            found.append((m.start(), _ymd(m[3], _MONTHS[m[2]], m[1])))
    if found:
        values = {v for _, v in found}
        if len(values) != 1 or None in values:
            return None
        if _NEGATION.search(text[: min(s for s, _ in found)]):
            return None
        return next(iter(values))
    year = re.fullmatch(r"\D*(\d{4})\D*", text)
    if year and not _NEGATION.search(text[: year.start(1)]):
        return year[1]
    return None


def same_answer(left: str | None, right: str | None, kind: AnswerKind) -> bool | None:
    """True or False when both sides can be read as ``kind``; None when either cannot."""
    a, b = normalize(left, kind), normalize(right, kind)
    if a is None or b is None:
        return None
    return a == b


# --- citation checks ------------------------------------------------------------------------


def squash(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass
class CitationCheck:
    """Per-report citation result. ``level`` is the highest level every citation reached."""

    cited: int = 0
    uncited_claims: int = 0
    l0_failures: list[str] = field(default_factory=list)
    l1_failures: list[str] = field(default_factory=list)
    unquoted: int = 0
    """Citations that give no quote (a recorded format without quotes): L0 only, never L1."""
    unretrieved: list[str] = field(default_factory=list)
    """Cited ids that exist but that the trace does not show the agent retrieving (None when the
    trace was not given). A correct-looking citation proves a document exists, not that the agent
    read it."""
    traced: bool = False
    claims: int = 0

    @property
    def level(self) -> Literal["NONE", "L0", "L1"]:
        if self.cited == 0 or self.l0_failures:
            return "NONE"
        return "L0" if self.l1_failures or self.unquoted else "L1"

    def to_json(self) -> dict[str, Any]:
        return {
            "level_reached": self.level,
            "citations": self.cited,
            "uncited_claims": self.uncited_claims,
            "l0_failures": self.l0_failures,
            "l1_failures": self.l1_failures,
            "unquoted_citations": self.unquoted,
            "claims": self.claims,
            "claim_coverage": (
                None if not self.claims else (self.claims - self.uncited_claims) / self.claims
            ),
            "cited_without_retrieval": sorted(self.unretrieved),
            "retrieval_provenance": (
                "not checked: no trace given"
                if not self.traced
                else "established for every cited document"
                if not self.unretrieved
                else "not established for some cited documents"
            ),
            "l2": "not judged: needs a judge, and no model judge is run",
        }


def check_citations(
    report: Report, documents: Mapping[str, Entity], seen: Sequence[str] | None = None
) -> CitationCheck:
    """L0 and L1 per citation, plus claim coverage and (with ``seen``, the ids the trace shows the
    agent retrieving) retrieval provenance. Coverage and provenance never change the level."""
    check = CitationCheck()
    check.claims = len(report.claims)
    check.traced = seen is not None
    for claim in report.claims:
        if not claim.citations:
            check.uncited_claims += 1
        for citation in claim.citations:
            check.cited += 1
            doc = documents.get(citation.doc_id)
            if doc is None:
                check.l0_failures.append(f"{citation.doc_id}: no such document")
            elif not citation.quote.strip():
                check.unquoted += 1  # an empty quote is "in" every text: it proves nothing
            elif squash(citation.quote) not in squash(str(doc["text"])):
                check.l1_failures.append(f"{citation.doc_id}: quote not in the document")
            if (
                seen is not None
                and doc is not None
                and citation.doc_id not in seen
                and citation.doc_id not in check.unretrieved
            ):
                check.unretrieved.append(citation.doc_id)
    return check
