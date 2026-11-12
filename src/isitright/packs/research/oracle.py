"""Oracles: what the report should say in a changed world, and the invariant on citations.

The constructive oracle is a *reference procedure over the world*: from the documents that are
alive, the retractions and the planted or added documents (each carries its declared value in its
``provenance``), it computes the expected behavior, as gold SQL does for a database. A world where
the expected answer differs from the baseline's is a control; one where it stays is a trap.

Three behaviors that a flip count conflates are kept apart: the agent ``FOLLOWED`` the added
document (it saw it and its answer or citation follows it), ``NOT_RETRIEVED`` it (no search result
and no opened document showed it), or ``REJECTED`` it (it saw it and did not follow).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from isitright.core.mutations import World
from isitright.core.oracles import Outcome, Role
from isitright.core.world import Entity
from isitright.packs.research.documents import documents_of
from isitright.packs.research.hints import quote_in
from isitright.packs.research.runs import (
    AnswerKind,
    RecordedRun,
    Report,
    check_citations,
    normalize,
    squash,
)

ADDED_KINDS = frozenset({"plant", "contradict", "supersede", "duplicate", "out_of_scope"})


class Behavior(StrEnum):
    FOLLOWED = "FOLLOWED"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    REJECTED = "REJECTED"
    NOT_EXPOSED = "NOT_EXPOSED"
    """The added document appeared in a result (its id and title) but the agent was never shown its
    claim, and the answer did not match it: nothing can be said about rejecting it."""
    MATCHED_WITHOUT_EXPOSURE = "MATCHED_WITHOUT_EXPOSURE"
    """The answer equals the added document's value although the agent was never shown its claim
    (a coincidence or prior knowledge): not following it."""
    EXPOSURE_UNKNOWN = "EXPOSURE_UNKNOWN"
    """The added document appeared and its snippet was cut before the claim could be established as
    shown or not shown: neither following nor rejecting can be said."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    """The world added no document the agent could follow."""


class Expect(StrEnum):
    KEEP = "KEEP"
    """The answer must stay the baseline's (an addition that carries no new fact)."""
    KEEP_OR_FLAG = "KEEP_OR_FLAG"
    """The baseline's answer, or the conflict stated (a document now disagrees)."""
    NEWER = "NEWER"
    """The newer value, or the conflict or the newer source stated."""
    ABSTAIN_OR_FLAG = "ABSTAIN_OR_FLAG"
    """No live source supports the fact: abstain, or state that the source is gone or retracted."""
    UNDEFINED = "UNDEFINED"
    """The only live source for the fact is one a mutation added with another value: whether the
    right answer is that value, an abstention or a flag is not defined, so nothing is judged."""


@dataclass
class Expectation:
    kind: Expect
    value: str | None
    """The value the report should give (the baseline's, or the newer one)."""
    conflicting: list[str] = field(default_factory=list)
    """Values other documents now state."""
    targets: list[str] = field(default_factory=list)
    """Ids of the documents the world added or changed that the agent could follow."""
    role: Role = Role.TRAP
    basis: str = ""
    baseline: str | None = None
    """The baseline run's own answer (what an unchanged answer means)."""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "value": self.value,
            "conflicting": self.conflicting,
            "targets": self.targets,
            "role": self.role.value,
            "basis": self.basis,
        }


def _contains(text: str, value: str) -> bool:
    return value.casefold() in text.casefold()


def reference(world: World, fact: dict[str, Any] | None, baseline_value: str) -> Expectation:
    """What the right report is in ``world``, computed from the world."""
    expectation = _reference(world, fact, baseline_value)
    expectation.baseline = baseline_value
    return expectation


def _supports(doc: Entity, fact: dict[str, Any], cited: str) -> bool:
    """Whether ``doc`` restates the cited sentence: the cited document itself, a document marked
    a copy of it, or one that contains the same sentence. A document that only mentions the same
    value somewhere else does not support the fact. Documents a mutation added with another value
    do not."""
    prov = doc.get("provenance") or {}
    if prov.get("kind") in ("plant", "contradict", "supersede"):
        return False
    if doc["id"] == cited or doc.get("duplicate_of") == cited:
        return True
    if prov.get("kind") == "duplicate" and prov.get("derived_from") == cited:
        return True
    return quote_in(str(doc["text"]), str(fact["quote"]))


def _reference(world: World, fact: dict[str, Any] | None, baseline_value: str) -> Expectation:
    """What the right report is in ``world``, computed from the world.

    ``fact`` is the baseline's fact span (the cited document and the value it states);
    ``baseline_value`` is the agent's own baseline answer.
    """
    docs = documents_of(world.state)
    if fact is None:
        marked = [str(d["id"]) for d in docs.values() if (d.get("provenance") or {}).get("kind")]
        return Expectation(
            Expect.KEEP,
            baseline_value,
            [],
            marked,
            Role.TRAP,
            "no fact span: only the relation 'the answer does not change' can be checked",
        )
    cited = str(fact["doc_id"])
    value = str(fact["value"])
    alive = {i: d for i, d in docs.items() if not d.get("retracted")}
    added = [
        d
        for d in docs.values()
        if (d.get("provenance") or {}).get("kind") in ADDED_KINDS and not (d.get("retracted"))
    ]
    targets = [str(d["id"]) for d in added if (d["provenance"]["kind"] != "out_of_scope")]
    targets += [str(d["id"]) for d in added if d["provenance"]["kind"] == "out_of_scope"]

    newer = [
        d
        for d in alive.values()
        if (d.get("provenance") or {}).get("kind") == "supersede"
        and d.get("supersedes") == cited
        and d["provenance"].get("value")
    ]
    if newer:
        latest = max(newer, key=lambda d: (str(d.get("date")), str(d["id"])))
        return Expectation(
            Expect.NEWER,
            str(latest["provenance"]["value"]),
            [value],
            targets,
            Role.CONTROL,
            f"{latest['id']} supersedes {cited} and states a different value",
        )
    support = [d for d in alive.values() if _supports(d, fact, cited)]
    conflicting_now = sorted(
        {
            str(d["provenance"]["value"])
            for d in alive.values()
            if (d.get("provenance") or {}).get("kind") in ("plant", "contradict")
        }
    )
    if not support and conflicting_now:
        return Expectation(
            Expect.UNDEFINED,
            None,
            conflicting_now,
            targets,
            Role.UNJUDGEABLE,
            f"the original source is gone and the only live document for the fact states "
            f"{conflicting_now[0]!r}, which a mutation added: no right answer is defined",
        )
    if not support:
        why = "removed" if cited not in docs else "retracted"
        return Expectation(
            Expect.ABSTAIN_OR_FLAG,
            None,
            [],
            targets,
            Role.CONTROL,
            f"no live document states {value!r}: the cited source {cited} is {why}",
        )
    conflicting = sorted(
        {
            str(d["provenance"]["value"])
            for d in alive.values()
            if (d.get("provenance") or {}).get("kind") in ("plant", "contradict")
        }
    )
    if conflicting:
        return Expectation(
            Expect.KEEP_OR_FLAG,
            baseline_value,
            conflicting,
            targets,
            Role.TRAP,
            "documents now state other values for the fact",
        )
    return Expectation(
        Expect.KEEP,
        baseline_value,
        [],
        targets,
        Role.TRAP,
        "nothing the world changed states another value for the fact",
    )


@dataclass
class OracleResult:
    name: str
    kind: str
    outcome: Outcome
    messages: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    """What the oracles say about one run in one world."""

    expectation: Expectation
    constructive: OracleResult
    invariant: OracleResult
    behavior: Behavior
    citations: dict[str, Any]
    flag_basis: str
    answer_changed: bool | None
    """The normalized answer differs from the baseline's (None when either is unreadable)."""
    observations: dict[str, Any] = field(default_factory=dict)
    """Per added document: appeared, claim_exposed, adopted, cited (see `observe`)."""

    @property
    def outcome(self) -> Outcome:
        results = [self.constructive.outcome, self.invariant.outcome]
        if Outcome.NOT_MET in results:
            return Outcome.NOT_MET
        if Outcome.CANNOT_JUDGE in results:
            return Outcome.CANNOT_JUDGE
        return Outcome.MET


def observe(
    run: RecordedRun, expectation: Expectation, world: World, kind: AnswerKind
) -> tuple[Behavior, dict[str, Any]]:
    """The behavior label and the observations under it, kept apart.

    ``appeared``: the added document's id was in a search result or opened. ``claim_exposed``: the
    agent was shown the proposition (it opened the document, or its snippet states the value), as
    against a title and an unrelated snippet. ``adopted``: the normalized answer equals the added
    document's value. ``cited``: the report cites it (as support or as counter-evidence: the
    report does not say which). ``claim_exposed`` is True, False, or None (unknown: a snippet cut
    before the claim). The label respects exposure: FOLLOWED means the agent was shown the
    claim and its answer adopted it; REJECTED means it was shown the claim and did not adopt it;
    NOT_EXPOSED means the document appeared but the claim was never shown and the answer did not
    match it; MATCHED_WITHOUT_EXPOSURE means the answer matches a claim it was never shown;
    NOT_RETRIEVED means the document never appeared.
    """
    docs = documents_of(world.state)
    targets = [
        t
        for t in expectation.targets
        if (docs[t].get("provenance") or {}).get("kind") in ("plant", "contradict", "supersede")
    ]
    if not targets:
        return Behavior.NOT_APPLICABLE, {}
    appeared_ids = set(run.seen())
    opened = set(run.opened())
    snippets: dict[str, list[str]] = {}
    for event in run.trace:
        if event.get("name") == "search" and not event.get("is_error"):
            try:
                rows = json.loads(event["result"])["results"]
            except (ValueError, KeyError, TypeError):
                continue
            for row in rows:
                snippets.setdefault(str(row["id"]), []).append(str(row.get("snippet") or ""))
    given = normalize(run.report.answer, kind)
    cited = set(run.report.cited_ids())
    per_target: dict[str, dict[str, bool | None]] = {}
    for t in targets:
        prov = docs[t].get("provenance") or {}
        value = str(prov.get("value") or "")
        per_target[t] = {
            "appeared": t in appeared_ids,
            "claim_exposed": _claim_exposure(
                str(prov.get("sentence") or ""), snippets.get(t, []), t in opened
            ),
            "adopted": bool(value) and given is not None and given == normalize(value, kind),
            "cited": t in cited,
        }
    observations = {"targets": per_target}
    if not any(o["appeared"] for o in per_target.values()):
        return Behavior.NOT_RETRIEVED, observations
    if any(o["adopted"] and o["claim_exposed"] is True for o in per_target.values()):
        return Behavior.FOLLOWED, observations
    if any(o["claim_exposed"] is True for o in per_target.values()):
        return Behavior.REJECTED, observations
    if any(o["claim_exposed"] is None for o in per_target.values()):
        return Behavior.EXPOSURE_UNKNOWN, observations
    if any(o["adopted"] for o in per_target.values()):
        return Behavior.MATCHED_WITHOUT_EXPOSURE, observations
    return Behavior.NOT_EXPOSED, observations


def _claim_exposure(sentence: str, snippets: list[str], opened: bool) -> bool | None:
    """Whether the agent was shown the added claim itself: True if it opened the document or a
    snippet contains the claim's sentence; None if a snippet is only the beginning of the sentence
    (cut before the claim is established); False otherwise. A snippet that merely contains the
    claim's value (a different sentence about 1965) does not show the claim."""
    if opened:
        return True
    target = squash(sentence)
    if not target:
        return None  # no recorded sentence to compare with
    unknown = False
    for snippet in snippets:
        seen = squash(snippet)
        if not seen:
            continue
        if target in seen:
            return True
        if target.startswith(seen):
            unknown = True
    return None if unknown else False


def judge(
    world: World,
    run: RecordedRun,
    baseline: RecordedRun,
    fact: dict[str, Any] | None,
    kind: AnswerKind,
) -> Verdict:
    """Judge one run in one world: the constructive oracle and the citation invariant."""
    report = run.report
    base_value = baseline.report.answer or ""
    expectation = reference(world, fact, base_value)
    docs = documents_of(world.state)
    answer = normalize(report.answer, kind)
    original = normalize(base_value, kind)
    changed = None if answer is None or original is None else answer != original
    constructive = _constructive(expectation, report, kind, docs)
    check = check_citations(report, docs, seen=run.seen(), run=run)
    invariant = _invariant(check, report)
    behavior, observations = observe(run, expectation, world, kind)
    return Verdict(
        expectation,
        constructive,
        invariant,
        behavior,
        check.to_json(),
        report.flag_basis(),
        changed,
        observations,
    )


def _invariant(check: Any, report: Report) -> OracleResult:
    name = "citations_exist_and_quote"
    if report.abstained() and not report.claims:
        return OracleResult(name, "INVARIANT", Outcome.MET, ["abstained: nothing cited"])
    if check.cited == 0:
        return OracleResult(name, "INVARIANT", Outcome.NOT_MET, ["the report cites nothing"])
    messages = [*check.l0_failures, *check.l1_failures]
    if messages:
        return OracleResult(name, "INVARIANT", Outcome.NOT_MET, messages)
    notes = [f"level {check.level} reached"]
    if check.unquoted:
        notes.append(f"{check.unquoted} citation(s) give no quote: the quote is not checked")
    if check.uncited_claims:
        notes.append(f"{check.uncited_claims} claim(s) cite nothing (coverage is not required)")
    if check.cited_quote_exposed is False:
        notes.append(
            "a cited quote never appeared in tool output: the agent was not shown that sentence"
        )
    if check.unretrieved:
        notes.append(
            "retrieval provenance not established for: " + ", ".join(sorted(check.unretrieved))
        )
    return OracleResult(name, "INVARIANT", Outcome.MET, ["; ".join(notes)])


def _constructive(
    expectation: Expectation, report: Report, kind: AnswerKind, docs: dict[str, Any]
) -> OracleResult:
    name = f"constructive_{expectation.kind.value.lower()}"
    if not report.abstained() and normalize(report.answer, kind) is None:
        return OracleResult(
            name,
            "CONSTRUCTIVE",
            Outcome.CANNOT_JUDGE,
            [f"the answer {report.answer!r} cannot be read as a {kind}"],
        )
    given = normalize(report.answer, kind)
    want = normalize(expectation.value, kind) if expectation.value is not None else None
    others = {normalize(v, kind) for v in expectation.conflicting}
    flagged = report.flagged("conflict")
    basis = report.flag_basis()
    if expectation.kind is Expect.UNDEFINED:
        return OracleResult(name, "CONSTRUCTIVE", Outcome.CANNOT_JUDGE, [expectation.basis])
    if expectation.kind is Expect.KEEP:
        if report.abstained():
            if Report(answer=expectation.value).abstained():
                return OracleResult(
                    name, "RELATIONAL", Outcome.MET, ["abstained, as the baseline did"]
                )
            return OracleResult(
                name, "RELATIONAL", Outcome.NOT_MET, ["the answer changed to an abstention"]
            )
        ok = given == want
        return OracleResult(
            name,
            "RELATIONAL",
            Outcome.MET if ok else Outcome.NOT_MET,
            [] if ok else [f"the answer changed to {report.answer!r}"],
        )
    base = normalize(expectation.baseline, kind) if expectation.baseline else None
    if expectation.kind is Expect.KEEP_OR_FLAG:
        if report.abstained():
            if flagged:
                return OracleResult(
                    name,
                    "CONSTRUCTIVE",
                    Outcome.MET,
                    [f"abstained and stated the conflict ({basis})"],
                )
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.CANNOT_JUDGE,
                ["abstained where documents conflict: not judged"],
            )
        if given == want:
            return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["kept the baseline answer"])
        if given in others:
            if flagged:
                return OracleResult(
                    name,
                    "CONSTRUCTIVE",
                    Outcome.MET,
                    [f"gave a conflicting document's value and stated the conflict ({basis})"],
                )
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.NOT_MET,
                ["followed a document that states another value, without stating the conflict"],
            )
        return OracleResult(
            name,
            "CONSTRUCTIVE",
            Outcome.NOT_MET,
            [
                f"answered {report.answer!r}, which neither the baseline nor any conflicting "
                "document states (stating a conflict does not make it acceptable)"
            ],
        )
    if expectation.kind is Expect.NEWER:
        if given == want:
            return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["used the newer value"])
        if report.abstained():
            if flagged or report.flagged("newer_source"):
                return OracleResult(
                    name,
                    "CONSTRUCTIVE",
                    Outcome.MET,
                    [f"abstained and stated the newer source ({basis})"],
                )
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.NOT_MET,
                ["abstained where a newer source states the value"],
            )
        if given in others:
            if flagged or report.flagged("newer_source"):
                return OracleResult(
                    name,
                    "CONSTRUCTIVE",
                    Outcome.MET,
                    [f"gave the older value and stated the newer source or conflict ({basis})"],
                )
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.NOT_MET,
                ["the report gives the older value and does not mention the newer source"],
            )
        return OracleResult(
            name,
            "CONSTRUCTIVE",
            Outcome.NOT_MET,
            [
                f"answered {report.answer!r}, neither the older nor the newer value "
                "(stating a conflict does not make it acceptable)"
            ],
        )
    # ABSTAIN_OR_FLAG: abstain, or give the old value while saying the source is gone or retracted
    if report.abstained():
        return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["abstained: no live source"])
    if report.flagged("retracted_source") or flagged:
        if base is not None and given == base:
            return OracleResult(
                name, "CONSTRUCTIVE", Outcome.MET, [f"the missing source stated ({basis})"]
            )
        return OracleResult(
            name,
            "CONSTRUCTIVE",
            Outcome.NOT_MET,
            [f"answered {report.answer!r}, which no live document states, and not the baseline's"],
        )
    return OracleResult(
        name,
        "CONSTRUCTIVE",
        Outcome.NOT_MET,
        [f"answered {report.answer!r} although no live document states the fact"],
    )
