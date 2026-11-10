"""Hints for the research pack and the span helpers the mutators use.

Hints come from the question text, the corpus metadata and the agent's baseline trace (the
documents it opened and the quote it cited). Never from the gold answer and never from what an
audit later finds. A hint names a fact span: the cited sentence and the value inside it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from isitright.core.entities import EntitySchema, ModelError
from isitright.core.hints import Hint, HintKind, Hints, Provenance, register_hint_kind
from isitright.packs.research.runs import (
    _NUMBER,
    AnswerKind,
    RecordedRun,
    normalize,
    squash,
)

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "with",
    ]
)


def _need(hint: Hint, *names: str) -> None:
    missing = [n for n in names if n not in hint.args]
    if missing:
        raise ModelError(f"hint {hint.name!r} ({hint.kind}) needs {', '.join(missing)}")


def _check_fact_span(_: EntitySchema, hint: Hint) -> None:
    """The sentence a baseline run cited and the value inside it: ``doc_id``, ``quote``,
    ``value``, ``answer_type``; optionally a declared ``alternative`` value."""
    _need(hint, "doc_id", "quote", "value", "answer_type")
    if hint.args["value"] not in hint.args["quote"]:
        raise ModelError(f"hint {hint.name!r}: the value is not inside the quote")


def _check_cited(_: EntitySchema, hint: Hint) -> None:
    """Document ids the baseline run opened or cited: ``ids``."""
    _need(hint, "ids")


def _check_terms(_: EntitySchema, hint: Hint) -> None:
    """The question's key terms: ``terms``."""
    _need(hint, "terms")


for _kind, _check in (
    ("fact_span", _check_fact_span),
    ("cited", _check_cited),
    ("question_terms", _check_terms),
):
    register_hint_kind(HintKind(_kind, _check))


def question_terms(question: str) -> list[str]:
    """Content words of the question in order, without duplicates."""
    seen: list[str] = []
    for word in re.findall(r"[\w'-]+", question):
        if word.casefold() not in STOPWORDS and word.casefold() not in {s.casefold() for s in seen}:
            seen.append(word)
    return seen


_DATE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b[A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]{2,8}\.?,?\s+\d{4}\b"),
    re.compile(r"\b\d{4}\b"),
)


def locate_value(quote: str, answer: str, kind: AnswerKind) -> str | None:
    """The text inside ``quote`` that is the answer, as written there, or None."""
    wanted = normalize(answer, kind)
    if wanted is None:
        return None
    if kind == "string":
        match = re.search(re.escape(answer.strip()), quote, re.IGNORECASE)
        return match.group() if match else None
    if kind == "number":
        for match in _NUMBER.finditer(quote):
            if normalize(match.group(), "number") == wanted:
                return match.group()
        return None
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(quote):
            if normalize(match.group(), "date") == wanted:
                return match.group()
    return None


def fact_span_from_run(
    run: RecordedRun, kind: AnswerKind, documents: Mapping[str, Mapping[str, Any]] | None = None
) -> Hint | None:
    """A ``fact_span`` hint from a baseline run: the first citation whose quote holds the answer.
    The answer is the agent's own, not the gold. With ``documents``, only a citation that exists
    in the corpus and whose quote occurs in it can give a span (an invented citation cannot)."""
    answer = run.report.answer
    if answer is None or run.report.abstained():
        return None
    for claim in run.report.claims:
        for citation in claim.citations:
            if documents is not None:
                doc = documents.get(citation.doc_id)
                if doc is None or not quote_in(str(doc["text"]), citation.quote):
                    continue
            value = locate_value(citation.quote, answer, kind)
            if value:
                return Hint(
                    kind="fact_span",
                    provenance=Provenance.HARVESTED_TRACE,
                    args={
                        "doc_id": citation.doc_id,
                        "quote": citation.quote,
                        "value": value,
                        "answer_type": kind,
                    },
                )
    return None


def hints_from_run(
    run: RecordedRun,
    kind: AnswerKind,
    question: str,
    documents: Mapping[str, Mapping[str, Any]] | None = None,
) -> Hints:
    hints = [
        Hint(
            kind="question_terms",
            provenance=Provenance.HARVESTED_QUESTION,
            args={"terms": question_terms(question)},
        )
    ]
    cited = list(dict.fromkeys([*run.report.cited_ids(), *run.opened()]))
    if cited:
        hints.append(Hint(kind="cited", provenance=Provenance.HARVESTED_TRACE, args={"ids": cited}))
    fact = fact_span_from_run(run, kind, documents)
    if fact is not None:
        hints.append(fact)
    return Hints(hints)


# --- alternative values ---------------------------------------------------------------------


def _year_like(text: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", text)) and 1000 <= int(text) <= 2200


def alternative_value(value: str, kind: AnswerKind, context: str) -> str | None:
    """A different value of the same kind, built deterministically; None when none can be made.

    number: a year moves three years, any other number is scaled by 1.15 and rounded to the same
    number of decimals (a number below 1 becomes 1 more). date: the year moves by one. string:
    another capitalized phrase of the same word count from ``context``.
    """
    if kind == "number":
        if _year_like(value):
            return str(int(value) + 3)
        digits = value.replace(",", "")
        try:
            number = float(digits)
        except ValueError:
            return None
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        new = round(number * 1.15 if abs(number) >= 1 else number + 1, decimals)
        if new == number:
            new = number + 10**-decimals
        text = f"{new:.{decimals}f}"
        if "," in value:
            whole, _, frac = text.partition(".")
            text = f"{int(whole):,}" + (f".{frac}" if frac else "")
        return text
    if kind == "date":
        years = re.findall(r"\d{4}", value)
        if not years:
            return None
        return re.sub(r"\d{4}", lambda m: str(int(m.group()) + 1), value, count=1)
    words = value.split()
    pattern = r"\b[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){" + str(len(words) - 1) + r"}\b"
    for match in re.finditer(pattern, context):
        if match.group().casefold() != value.casefold():
            return match.group()
    return None


# --- spans ----------------------------------------------------------------------------------


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    """Where ``quote`` occurs in ``text``, tolerant of whitespace and case."""
    pieces = quote.split()
    if not pieces:
        return None
    match = re.search(r"\s+".join(re.escape(p) for p in pieces), text, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def replace_value(sentence: str, value: str, new_value: str) -> str | None:
    match = re.search(re.escape(value), sentence)
    if match is None:
        match = re.search(re.escape(value), sentence, re.IGNORECASE)
    if match is None:
        return None
    return sentence[: match.start()] + new_value + sentence[match.end() :]


def edit_span(text: str, quote: str, value: str, new_value: str) -> tuple[str, str, str] | None:
    """``text`` with the value inside the quoted sentence replaced, plus the old and new sentence.
    None when the quote or the value is not found."""
    span = find_span(text, quote)
    if span is None:
        return None
    old = text[span[0] : span[1]]
    new = replace_value(old, value, new_value)
    if new is None:
        return None
    return text[: span[0]] + new + text[span[1] :], old, new


def later_date(day: str | None, cutoff: str | None, days: int = 30) -> str | None:
    """A date ``days`` after ``day``, capped at ``cutoff``; None without a ``day``."""
    if not day:
        return None
    start = date.fromisoformat(str(day)[:10])
    moved = date.fromordinal(start.toordinal() + days)
    if cutoff:
        moved = min(moved, date.fromisoformat(cutoff[:10]))
    return moved.isoformat()


def quote_in(text: str, quote: str) -> bool:
    return squash(quote) in squash(text)


def fact(hints: Hints) -> Mapping[str, Any] | None:
    found = hints.of("fact_span")
    return found[0].args if found else None
