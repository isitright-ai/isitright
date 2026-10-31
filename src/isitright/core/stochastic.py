"""Stochastic subjects: budgets, repeated runs, counts and rate claims.

A live agent can pass and fail on the same world. Outcomes are counts (6 of 8), a flaky baseline
is reported first, and a *rate* claim needs enough paired evidence and a stated test. Below that,
only counts are reported. An observed failure is never turned into a rate change.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.oracles import Outcome
from isitright.core.sequential import Decision, PairedSprt, SequentialRecord
from isitright.core.subjects import Cost

DEFAULT_K = 4
MIN_PAIRS_FOR_RATE_CLAIM = 8
ALPHA = 0.05


class Counts(BaseModel):
    """What happened in n runs of one world. Counts only."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=0)
    met: int = Field(ge=0)
    not_met: int = Field(ge=0)
    cannot_judge: int = Field(ge=0)
    violated: int = Field(ge=0)
    errors: int = Field(ge=0)


class RateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test: str
    paired_runs: int
    discordant_baseline_only: int
    discordant_world_only: int
    p_value: float
    alpha: float


class Stability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int
    baseline: Counts | None = None
    world: Counts | None = None
    rate_claim: RateClaim | None = None
    sequential: SequentialRecord | None = None
    """The sequential test behind a world's run count: looks, boundaries, decision (0.5)."""
    note: str = ""


@dataclass(frozen=True)
class RunOutcome:
    """The verdict of one run: the main oracle's outcome, invariant violations, errors, cost."""

    outcome: Outcome | None
    violated: bool = False
    error: bool = False
    cost: Cost = field(default_factory=Cost)


def count(outcomes: list[RunOutcome]) -> Counts:
    return Counts(
        n=len(outcomes),
        met=sum(o.outcome is Outcome.MET and not o.error for o in outcomes),
        not_met=sum(o.outcome is Outcome.NOT_MET for o in outcomes),
        cannot_judge=sum(o.outcome is Outcome.CANNOT_JUDGE for o in outcomes),
        violated=sum(o.violated for o in outcomes),
        errors=sum(o.error for o in outcomes),
    )


def is_bad(outcome: RunOutcome) -> bool:
    """An observed failure: an invariant violation or an expected behavior not reached."""
    return outcome.violated or outcome.outcome is Outcome.NOT_MET


def mcnemar_exact(only_baseline: int, only_world: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs (a binomial test at p = 1/2)."""
    n = only_baseline + only_world
    if n == 0:
        return 1.0
    low = min(only_baseline, only_world)
    tail = sum(math.comb(n, i) for i in range(low + 1)) / 2**n
    return float(min(1.0, 2 * tail))


def rate_claim(baseline: list[RunOutcome], world: list[RunOutcome]) -> RateClaim | None:
    """A paired comparison of failure between baseline and world, or None without enough evidence.

    Runs are paired by trial index. Fewer than MIN_PAIRS_FOR_RATE_CLAIM pairs, a p-value at or
    above ALPHA, or more discordant pairs in the baseline's favor give no claim of a higher failure
    rate in the world.
    """
    pairs = min(len(baseline), len(world))
    if pairs < MIN_PAIRS_FOR_RATE_CLAIM:
        return None
    only_baseline = sum(is_bad(b) and not is_bad(w) for b, w in zip(baseline, world, strict=False))
    only_world = sum(is_bad(w) and not is_bad(b) for b, w in zip(baseline, world, strict=False))
    p_value = mcnemar_exact(only_baseline, only_world)
    if p_value >= ALPHA or only_world <= only_baseline:
        return None
    return RateClaim(
        test="exact McNemar test on paired runs",
        paired_runs=pairs,
        discordant_baseline_only=only_baseline,
        discordant_world_only=only_world,
        p_value=p_value,
        alpha=ALPHA,
    )


def stability(baseline: list[RunOutcome] | None, world: list[RunOutcome], k: int) -> Stability:
    claim = rate_claim(baseline, world) if baseline else None
    if baseline is None:
        note = "no baseline runs: counts only"
    elif claim is None and len(baseline) < MIN_PAIRS_FOR_RATE_CLAIM:
        note = (
            f"{len(baseline)} paired runs is below the {MIN_PAIRS_FOR_RATE_CLAIM} needed for a "
            "rate claim: counts only"
        )
    elif claim is None:
        note = "no significant increase over the baseline: counts only"
    else:
        note = "paired comparison supports a higher failure rate in this world"
    flaky = baseline is not None and 0 < sum(is_bad(b) for b in baseline) < len(baseline)
    if flaky:
        note = "the baseline itself is flaky, which weakens any finding. " + note
    return Stability(
        k=k,
        baseline=count(baseline) if baseline is not None else None,
        world=count(world),
        rate_claim=claim,
        note=note,
    )


def stability_sequential(
    baseline: list[RunOutcome], world: list[RunOutcome], k: int, test: PairedSprt
) -> Stability:
    """Stability for a world run in pairs with a sequential test: counts, and a rate claim only
    when the test crossed its upper boundary."""
    record = test.record()
    claim = None
    if test.decision is Decision.RATE_INCREASE:
        claim = RateClaim(
            test=record.test,
            paired_runs=record.pairs,
            discordant_baseline_only=record.discordant_baseline_only,
            discordant_world_only=record.discordant_world_only,
            p_value=record.p_value,
            alpha=record.alpha,
        )
    flaky = 0 < sum(is_bad(b) for b in baseline) < len(baseline)
    note = record.note
    if flaky:
        note = "the baseline itself is flaky, which weakens any finding. " + note
    return Stability(
        k=k,
        baseline=count(baseline),
        world=count(world),
        rate_claim=claim,
        sequential=record,
        note=note,
    )


BudgetLimit = Literal["attempts", "runs", "seconds", "money"]


class Budget:
    """Limits in attempts, runs, wall time and money. ``None`` means unlimited."""

    def __init__(
        self,
        attempts: int | None = None,
        runs: int | None = None,
        seconds: float | None = None,
        money: float | None = None,
    ) -> None:
        self.attempts, self.runs, self.seconds, self.money = attempts, runs, seconds, money
        self.spent_attempts = 0
        self.spent_runs = 0
        self.spent_money = 0.0
        self._start = time.monotonic()
        self.exhausted: BudgetLimit | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def _check(self) -> BudgetLimit | None:
        if self.money is not None and self.spent_money >= self.money:
            self.exhausted = "money"
        elif self.seconds is not None and self.elapsed() >= self.seconds:
            self.exhausted = "seconds"
        elif self.runs is not None and self.spent_runs >= self.runs:
            self.exhausted = "runs"
        elif self.attempts is not None and self.spent_attempts >= self.attempts:
            self.exhausted = "attempts"
        return self.exhausted

    def can_attempt(self) -> bool:
        return self._check() is None

    def can_run(self) -> bool:
        return self._check() is None

    def attempt(self) -> None:
        self.spent_attempts += 1

    def record_run(self, cost: Cost) -> None:
        self.spent_runs += 1
        self.spent_money += cost.money

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "limits": {
                "attempts": self.attempts,
                "runs": self.runs,
                "seconds": self.seconds,
                "money": self.money,
            },
            "spent": {
                "attempts": self.spent_attempts,
                "runs": self.spent_runs,
                "money": round(self.spent_money, 6),
            },
            "stopped_by": self.exhausted,
        }
        if self.seconds is not None:
            spent = out["spent"]
            assert isinstance(spent, dict)
            spent["seconds"] = round(self.elapsed(), 3)
        return out


def run_repeated(run_once: Callable[[int], RunOutcome], k: int, budget: Budget) -> list[RunOutcome]:
    """Up to k runs of one world, stopping early when the run or money budget is spent."""
    outcomes: list[RunOutcome] = []
    for trial in range(k):
        if not budget.can_run():
            break
        outcome = run_once(trial)
        budget.record_run(outcome.cost)
        outcomes.append(outcome)
    return outcomes
