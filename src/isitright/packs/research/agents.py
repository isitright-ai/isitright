# Proposed fixture: pending owner review
# The stand-in agents below were written by Claude, not by the owner and not by an agent vendor.
# Every result that comes from them says so. Their behavior is a declared simplification.
"""The task, the tool client and the stand-in agents.

A stand-in agent is a small deterministic program with a declared behavior. They exist so that the
audit can be tested offline and so that controls and traps can be shown to separate careless from
careful behavior. They read documents with a rule the task declares (``reader_pattern``): the
sentence that shares most terms with the question, and the first match of the pattern in it.
Nothing here calls a model.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from isitright.packs.research.hints import question_terms
from isitright.packs.research.retrieval import ToolHost, tokenize
from isitright.packs.research.runs import (
    AnswerKind,
    Citation,
    Claim,
    Report,
    SubjectLabel,
)

WRITTEN_BY = "Claude (an AI assistant), as a stand-in; not a real research agent"


class ResearchTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    answer_type: AnswerKind = "string"
    gold: str | None = None
    gold_basis: str = "not checked: taken as given by whoever wrote the task"
    """Whether the gold answer was checked against anything. Stated in every finding."""
    reader_pattern: str | None = None
    """Used by the stand-in agents only: a regex whose first group (or whole match) is the value."""
    cutoff: str | None = None


class ToolClient:
    """What an in-process agent sees: the two tools of one world, with every call recorded."""

    def __init__(self, host: ToolHost) -> None:
        self._host = host

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        text, error = self._host.try_call("search", {"query": query, "k": k})
        if error:
            return []
        rows: list[dict[str, Any]] = json.loads(text)["results"]
        return rows

    def open(self, doc_id: str) -> dict[str, Any] | None:
        text, error = self._host.try_call("open", {"id": doc_id})
        if error:
            return None
        value: dict[str, Any] = json.loads(text)
        return value


class Agent(Protocol):
    label: SubjectLabel
    stochastic: bool

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report: ...


@dataclass(frozen=True)
class Reading:
    value: str
    quote: str
    doc_id: str
    date: str | None
    authority: int
    retracted: bool


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def read_document(doc: dict[str, Any], task: ResearchTask) -> Reading | None:
    """The sentence of ``doc`` that contains every content word of the question and the value the
    task's pattern finds in it (the first such sentence); None when there is none. A sentence about
    another subject with the same shape is therefore not a reading."""
    if not task.reader_pattern:
        return None
    wanted = set(tokenize(" ".join(question_terms(task.question))))
    text = str(doc.get("text") or "")
    pattern = re.compile(task.reader_pattern)
    best: tuple[int, str, str] | None = None
    for sentence in _sentences(text):
        match = pattern.search(sentence)
        if match is None:
            continue
        overlap = len(wanted & set(tokenize(sentence)))
        if overlap < len(wanted):
            continue
        value = match.group(1) if match.groups() else match.group()
        if best is None or overlap > best[0]:
            best = (overlap, sentence, value)
    if best is None:
        return None
    return Reading(
        best[2],
        best[1],
        str(doc["id"]),
        doc.get("date"),
        int(doc.get("authority") or 0),
        "retracted" in text.casefold()[:200],
    )


def _report(
    reading: Reading, extra: list[Reading] | None = None, flags: list[str] | None = None
) -> Report:
    claims = [
        Claim(
            text=f"The answer is {r.value}.",
            citations=[Citation(doc_id=r.doc_id, quote=r.quote)],
        )
        for r in [reading, *(extra or [])]
    ]
    return Report(answer=reading.value, claims=claims, flags=flags)


class Careful:
    """Searches, opens every result, reads each, ignores retracted documents, prefers the newest
    (then the most authoritative) source, takes the majority on a tie of date and authority, and
    says so when sources disagree."""

    stochastic = False

    def __init__(self, k: int = 5) -> None:
        self.k = k
        self.label = SubjectLabel(
            kind="stand_in",
            name="careful",
            written_by=WRITTEN_BY,
            note="searches, opens all, cites verbatim, prefers newer sources, flags conflicts",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        readings: list[Reading] = []
        retracted_seen = False
        for row in tools.search(task.question, self.k):
            doc = tools.open(str(row["id"]))
            reading = read_document(doc, task) if doc else None
            if reading is None:
                continue
            if reading.retracted:
                retracted_seen = True
                continue
            readings.append(reading)
        if not readings:
            gone = ["retracted_source"] if retracted_seen else []
            return Report(answer="I cannot answer from the sources found.", flags=gone)
        values = {r.value.casefold() for r in readings}
        flags: list[str] = ["retracted_source"] if retracted_seen else []
        if len(values) == 1:
            return _report(readings[0], flags=flags)
        flags.append("conflict")
        newest = max(readings, key=lambda r: (r.date or "", r.authority))
        rivals = [
            r
            for r in readings
            if (r.date or "", r.authority) == (newest.date or "", newest.authority)
        ]
        if len({r.value.casefold() for r in rivals}) == 1:
            flags.append("newer_source")
            chosen = newest
        else:
            counts: dict[str, int] = {}
            for r in rivals:
                counts[r.value.casefold()] = counts.get(r.value.casefold(), 0) + 1
            best = max(counts.values())
            chosen = next(r for r in rivals if counts[r.value.casefold()] == best)
        others = [r for r in readings if r.value.casefold() != chosen.value.casefold()]
        return _report(chosen, others[:1], flags)


class Credulous:
    """Follows the top-ranked document: opens it, reads it, answers. Ignores dates and conflicts."""

    stochastic = False

    def __init__(self) -> None:
        self.label = SubjectLabel(
            kind="stand_in",
            name="credulous",
            written_by=WRITTEN_BY,
            note="opens the top-ranked result and answers from it; no dates, no conflict check",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        for row in tools.search(task.question, 5):
            doc = tools.open(str(row["id"]))
            reading = read_document(doc, task) if doc else None
            if reading is not None:
                return _report(reading)
            break
        return Report(answer="I cannot answer from the sources found.")


class SnippetReader:
    """Rank-sensitive on purpose: answers from the snippet of the first search result and never
    opens a document."""

    stochastic = False

    def __init__(self) -> None:
        self.label = SubjectLabel(
            kind="stand_in",
            name="snippet_reader",
            written_by=WRITTEN_BY,
            note="reads only the snippet of the first search result",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        rows = tools.search(task.question, 5)
        if rows:
            fake = {"id": rows[0]["id"], "text": rows[0]["snippet"]}
            reading = read_document(fake, task)
            if reading is not None:
                return _report(reading)
        return Report(answer="I cannot answer from the sources found.")


class NonRetrieving:
    """Answers from fixed knowledge and cites a document that does not exist."""

    stochastic = False

    def __init__(self, known_answer: str) -> None:
        self.known = known_answer
        self.label = SubjectLabel(
            kind="stand_in",
            name="non_retrieving",
            written_by=WRITTEN_BY,
            note="answers from a fixed string; its citation is invented",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        return Report(
            answer=self.known,
            claims=[
                Claim(
                    text=f"The answer is {self.known}.",
                    citations=[Citation(doc_id="doc-0000", quote=f"the answer is {self.known}")],
                )
            ],
        )


class Refusing:
    """Searches once and always says it cannot answer."""

    stochastic = False

    def __init__(self) -> None:
        self.label = SubjectLabel(
            kind="stand_in",
            name="refusing",
            written_by=WRITTEN_BY,
            note="always abstains",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        tools.search(task.question, 5)
        return Report(answer="I cannot answer this question.")


class Mixed:
    """Stochastic: on each run draws (seeded) whether to behave as the credulous or the careful
    stand-in. ``credulous_rate`` is the chance of the credulous behavior."""

    stochastic = True

    def __init__(self, credulous_rate: float = 0.5) -> None:
        self.rate = credulous_rate
        self._careful, self._credulous = Careful(), Credulous()
        self.label = SubjectLabel(
            kind="stand_in",
            name=f"mixed({credulous_rate})",
            written_by=WRITTEN_BY,
            note="draws credulous or careful behavior per run from a seeded generator",
        )

    def run(self, tools: ToolClient, task: ResearchTask, seed: int) -> Report:
        draw = random.Random(seed).random()
        agent = self._credulous if draw < self.rate else self._careful
        return agent.run(tools, task, seed)


STAND_INS: dict[str, Callable[[ResearchTask], Agent]] = {
    "careful": lambda t: Careful(),
    "credulous": lambda t: Credulous(),
    "snippet_reader": lambda t: SnippetReader(),
    "non_retrieving": lambda t: NonRetrieving(t.gold or "unknown"),
    "refusing": lambda t: Refusing(),
    "mixed": lambda t: Mixed(0.5),
}

StandInName = Literal[
    "careful", "credulous", "snippet_reader", "non_retrieving", "refusing", "mixed"
]
