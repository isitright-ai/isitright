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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from isitright.core.mutations import World
from isitright.core.oracles import Outcome, Role
from isitright.packs.research.documents import documents_of
from isitright.packs.research.runs import (
    AnswerKind,
    RecordedRun,
    Report,
    check_citations,
    normalize,
)

ADDED_KINDS = frozenset({"plant", "contradict", "supersede", "duplicate", "out_of_scope"})


class Behavior(StrEnum):
    FOLLOWED = "FOLLOWED"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    REJECTED = "REJECTED"
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
    support = [
        d
        for i, d in alive.items()
        if _contains(str(d["text"]), value)
        and (d.get("provenance") or {}).get("kind") not in ("plant", "contradict")
    ]
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

    @property
    def outcome(self) -> Outcome:
        results = [self.constructive.outcome, self.invariant.outcome]
        if Outcome.NOT_MET in results:
            return Outcome.NOT_MET
        if Outcome.CANNOT_JUDGE in results:
            return Outcome.CANNOT_JUDGE
        return Outcome.MET


def behavior_of(
    run: RecordedRun, expectation: Expectation, world: World, kind: AnswerKind
) -> Behavior:
    docs = documents_of(world.state)
    targets = [
        t
        for t in expectation.targets
        if (docs[t].get("provenance") or {}).get("kind") != "out_of_scope"
    ]
    if not targets:
        return Behavior.NOT_APPLICABLE
    seen = set(run.seen())
    shown = [t for t in targets if t in seen]
    if not shown:
        return Behavior.NOT_RETRIEVED
    cited = set(run.report.cited_ids())
    for target in shown:
        value = (docs[target].get("provenance") or {}).get("value")
        if target in cited:
            return Behavior.FOLLOWED
        if value and normalize(run.report.answer, kind) == normalize(str(value), kind):
            return Behavior.FOLLOWED
    return Behavior.REJECTED


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
    check = check_citations(report, docs)
    invariant = _invariant(check, report)
    return Verdict(
        expectation,
        constructive,
        invariant,
        behavior_of(run, expectation, world, kind),
        check.to_json(),
        report.flag_basis(),
        changed,
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
    note = f"level {check.level} reached"
    if check.unquoted:
        note += f" ({check.unquoted} citation(s) give no quote: the quote is not checked)"
    return OracleResult(name, "INVARIANT", Outcome.MET, [note])


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
    if expectation.kind is Expect.KEEP_OR_FLAG:
        if flagged:
            return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, [f"conflict stated ({basis})"])
        if report.abstained():
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.CANNOT_JUDGE,
                ["abstained where documents conflict: not judged"],
            )
        if given == want:
            return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["kept the baseline answer"])
        why = (
            "followed a document that states another value, without stating the conflict"
            if given in others
            else f"answered {report.answer!r}, neither the baseline's nor a conflicting value"
        )
        return OracleResult(name, "CONSTRUCTIVE", Outcome.NOT_MET, [why])
    if expectation.kind is Expect.NEWER:
        if given == want:
            return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["used the newer value"])
        if flagged or report.flagged("newer_source"):
            return OracleResult(
                name,
                "CONSTRUCTIVE",
                Outcome.MET,
                [f"the newer source or conflict stated ({basis})"],
            )
        return OracleResult(
            name,
            "CONSTRUCTIVE",
            Outcome.NOT_MET,
            ["the report gives the older value and does not mention the newer source"]
            if report.abstained() is False
            else ["abstained where a newer source states the value"],
        )
    # ABSTAIN_OR_FLAG
    if report.abstained():
        return OracleResult(name, "CONSTRUCTIVE", Outcome.MET, ["abstained: no live source"])
    if report.flagged("retracted_source") or flagged:
        return OracleResult(
            name, "CONSTRUCTIVE", Outcome.MET, [f"the missing source stated ({basis})"]
        )
    return OracleResult(
        name,
        "CONSTRUCTIVE",
        Outcome.NOT_MET,
        [f"answered {report.answer!r} although no live document states the fact"],
    )
