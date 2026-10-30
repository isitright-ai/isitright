"""Search: propose worlds from mutators, validate, run, and stop at the budget.

One search serves deterministic and live subjects. Hints prioritize: hinted mutations are visited
first, and unhinted ones run on the budget that remains. Composition goes to depth two: for each
parent that did not itself disagree, proposals are regenerated from the parent's state, so a
second mutation can act on what the first created. The first valid disagreement is returned (or
all of them, when asked), with an account of what was spent and skipped.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from isitright.core.constraints import Validity, ValidityStatus
from isitright.core.hints import Hints
from isitright.core.mutations import AddEntity, Candidate, EditError, Mutator, World
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget

FIRST_LEVEL_SHARE = 0.5


class Verdict(StrEnum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    ERROR = "ERROR"
    INCONCLUSIVE = "INCONCLUSIVE"
    """The comparison policy could not decide (never a counterexample)."""
    REJECTED = "REJECTED"
    """The host or the pack refused the world (a rule the core does not know)."""


@dataclass
class Evaluation:
    verdict: Verdict
    validity: Validity | None = None
    detail: Any = None
    reason: str = ""
    """Why a world was rejected or errored, for the accounting."""


@dataclass
class Finding:
    candidate: Candidate
    validity: Validity
    evaluation: Evaluation


@dataclass
class GroupAccount:
    candidates: int = 0
    executed: int = 0


@dataclass
class SearchResult:
    seed: int
    attempts: int = 0
    valid: int = 0
    executed: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    families_run: list[str] = field(default_factory=list)
    families_skipped: dict[str, str] = field(default_factory=dict)
    groups: dict[str, GroupAccount] = field(
        default_factory=lambda: {"hinted": GroupAccount(), "unhinted": GroupAccount()}
    )
    hints_used: list[str] = field(default_factory=list)
    depth_reached: int = 0
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strongest: Validity | None = None
    budget: Budget = field(default_factory=Budget)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def accounting(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "attempts": self.attempts,
            "valid_candidates": self.valid,
            "executed": self.executed,
            "rejected": dict(sorted(self.rejected.items())),
            "families_run": self.families_run,
            "families_skipped": self.families_skipped,
            "budget_by_group": {
                name: {"candidates": g.candidates, "executed": g.executed}
                for name, g in self.groups.items()
            },
            "hints_used": self.hints_used,
            "depth_reached": self.depth_reached,
            "notes": self.notes,
            "budget": self.budget.to_json(),
        }


Progress = Callable[[str], None]


def _created_atoms(parent: World) -> set[tuple[str, Any]]:
    """Atoms that the parent's own (last) mutation added to its state."""
    if not parent.path:
        return set()
    return {
        (edit.collection, edit.entity[parent.state.keys[edit.collection]])
        for edit in parent.path[-1].edits
        if isinstance(edit, AddEntity)
    }


def search(
    spec: WorldSpec,
    base: World,
    hints: Hints,
    mutators: Sequence[Mutator],
    evaluate: Callable[[Candidate, Validity], Evaluation],
    *,
    budget: Budget,
    seed: int = 0,
    depth: int = 2,
    stop_on_first: bool = True,
    compose_from: str = "agreeing",
    max_parents: int = 200,
    include_base: bool = False,
    validate: Callable[[World], Validity] | None = None,
    progress: Progress | None = None,
) -> SearchResult:
    """Visit candidate worlds in priority order until a finding or the budget.

    ``compose_from`` is ``agreeing`` (only parents that did not disagree) or ``all``.
    """
    rng = random.Random(seed)
    result = SearchResult(seed=seed, budget=budget)
    result.hints_used = [h.name for h in hints]
    seen = set() if include_base else {base.fingerprint()}
    check = validate or (lambda w: spec.validate(w.state))
    order = {m.family: i for i, m in enumerate(mutators)}
    produced: set[str] = set()
    parents: list[Candidate] = []

    def proposals(parent: World, level: int) -> list[tuple[tuple[int, int, int, int], Candidate]]:
        """Proposals from a parent world, each with its priority (smaller is visited first)."""
        out: list[tuple[tuple[int, int, int, int], Candidate]] = []
        used = {name for earlier in parent.path for name in earlier.hints}
        made = _created_atoms(parent)
        for mutator in mutators:
            try:
                mutations = list(mutator.propose(spec, parent, hints))
            except Exception as error:  # a family that cannot read this spec is skipped, noted
                result.families_skipped.setdefault(mutator.family, f"error: {error}")
                continue
            for mutation in mutations:
                produced.add(mutator.family)
                try:
                    child = parent.apply(mutation)
                except EditError:
                    result.reject("edit_not_applicable")
                    continue
                hinted = 0 if mutation.hints else 1
                # A second mutation that acts on what the first created, or that brings a hint
                # the path has not used yet, covers a new aspect of the task instead of repeating
                # the parent's; those come first within their hint group.
                acts = int(any(tuple(a) in made for a in mutation.atoms)) if level > 1 else 0
                novel = len(set(mutation.hints) - used) if level > 1 else 0
                priority = (hinted, -acts, -novel, order[mutator.family])
                out.append(
                    (priority, Candidate(child, "hinted" if hinted == 0 else "unhinted", level))
                )
        rng.shuffle(out)
        out.sort(key=lambda item: item[0])
        return out

    def visit(candidate: Candidate) -> bool:
        """Returns True when the search should stop."""
        if not budget.can_attempt():
            return True
        budget.attempt()
        result.attempts += 1
        result.groups[candidate.group].candidates += 1
        fingerprint = candidate.world.fingerprint()
        if fingerprint in seen:
            result.reject("duplicate_state")
            return False
        seen.add(fingerprint)
        validity = check(candidate.world)
        if validity.status is not ValidityStatus.VALID:
            result.reject(
                "validation_indeterminate"
                if validity.status is ValidityStatus.INDETERMINATE
                else "domain_constraint"
            )
            if validity.problems and len(result.errors) < 20:
                result.errors.append(validity.problems[0])
            if progress:
                progress("rejected")
            return False
        result.valid += 1
        family = candidate.world.path[-1].family if candidate.world.path else "baseline"
        if family not in result.families_run:
            result.families_run.append(family)
        result.depth_reached = max(result.depth_reached, candidate.depth)
        evaluation = evaluate(candidate, validity)
        if evaluation.verdict is Verdict.REJECTED:
            result.reject(evaluation.reason or "rejected_by_host")
            if progress:
                progress("rejected")
            return False
        result.executed += 1
        result.groups[candidate.group].executed += 1
        if evaluation.validity is not None:
            validity = evaluation.validity
        if result.strongest is None or len(validity.tiers) >= len(result.strongest.tiers):
            result.strongest = validity
        if progress:
            progress(
                {"AGREE": "agreement", "DISAGREE": "counterexample"}.get(
                    evaluation.verdict.value, "error"
                )
            )
        if evaluation.verdict is Verdict.DISAGREE:
            result.findings.append(Finding(candidate, validity, evaluation))
            if compose_from == "all" and candidate.depth < depth:
                parents.append(candidate)
            return stop_on_first
        if evaluation.verdict in (Verdict.ERROR, Verdict.INCONCLUSIVE):
            result.reject(evaluation.reason or evaluation.verdict.value.lower())
            return False
        if candidate.depth < depth:
            parents.append(candidate)
        return False

    stopped = False
    if include_base and visit(Candidate(base, "hinted", 0)):
        stopped = True
    # With composition on, single mutations get at most half of a finite attempt budget; the rest
    # is kept for second mutations, which single mutations alone could never reach.
    first_level_limit = (
        math.ceil(budget.attempts * FIRST_LEVEL_SHARE)
        if budget.attempts is not None and depth > 1
        else None
    )
    for _, candidate in [] if stopped else proposals(base, 1):
        if first_level_limit is not None and budget.spent_attempts >= first_level_limit:
            result.notes.append(
                f"single mutations stopped at {first_level_limit} attempts to leave budget for "
                "composed ones"
            )
            break
        if visit(candidate):
            stopped = True
            break
    level = 1
    while not stopped and level < depth and parents:
        level += 1
        current, parents[:] = parents[:max_parents], []
        pending = [item for p in current for item in proposals(p.world, level)]
        pending.sort(key=lambda item: item[0])
        for _, candidate in pending:
            if visit(candidate):
                stopped = True
                break
    for mutator in mutators:
        if mutator.family not in produced:
            result.families_skipped.setdefault(mutator.family, "no applicable mutation or hint")
    if not budget.can_attempt() and budget.exhausted:
        result.notes.append(f"stopped at the {budget.exhausted} budget")
    elif stopped and result.findings:
        result.notes.append("stopped at the first valid disagreement")
    return result
