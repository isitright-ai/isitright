"""Stochastic subjects: budgets, repeated runs, counts and rate claims.

A live agent can pass and fail on the same world. Outcomes are counts (6 of 8), a flaky baseline
is reported first, and a *rate* claim needs enough paired evidence and a stated test. Below that,
only counts are reported. An observed failure is never turned into a rate change.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.oracles import Outcome
from isitright.core.sequential import (
    Decision,
    PairedSprt,
    PairingInfo,
    SequentialRecord,
    SprtConfig,
)
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


class EvidenceGrade(StrEnum):
    """What a live-agent finding supports. The two grades are never merged."""

    RATE_INCREASE = "RATE_INCREASE"
    """A paired sequential test decided that the world fails more often than the baseline."""
    OBSERVED_FAILURE = "OBSERVED_FAILURE"
    """A judged run failed on a world that ran and was not found invalid. Actionable and
    replayable; it says nothing about a higher failure rate, because no test decided one, and it
    does not say the world was validated (see the world's own validity)."""


WILSON_Z = 1.959964
"""The 97.5th percentile of the normal distribution: a two-sided 95% interval."""


def wilson_interval(failures: int, runs: int) -> tuple[float, float] | None:
    """The 95% Wilson score interval of a failure rate, or None when there are no runs.

    Descriptive only: it treats the runs as independent draws with one failure probability and
    makes no allowance for the many worlds an audit looks at.
    """
    if runs <= 0:
        return None
    z2 = WILSON_Z**2
    p = failures / runs
    centre = (p + z2 / (2 * runs)) / (1 + z2 / runs)
    half = WILSON_Z * math.sqrt(p * (1 - p) / runs + z2 / (4 * runs**2)) / (1 + z2 / runs)
    return max(0.0, centre - half), min(1.0, centre + half)


class RateWithInterval(BaseModel):
    """failures / judged runs, with errors and unjudged runs beside them and a Wilson interval."""

    model_config = ConfigDict(extra="forbid")

    failures: int = Field(ge=0)
    judged: int = Field(ge=0)
    errors: int = Field(ge=0)
    unjudged: int = Field(ge=0)
    rate: float | None = None
    interval_low: float | None = None
    interval_high: float | None = None
    interval: str = "95% Wilson score interval, descriptive"


def rate_with_interval(outcomes: list[RunOutcome]) -> RateWithInterval:
    """Counts of one set of runs. Errored and unjudged runs are not in the denominator."""
    errors = sum(o.error for o in outcomes)
    judged = [o for o in outcomes if is_judged(o)]
    failures = sum(is_bad(o) for o in judged)
    interval = wilson_interval(failures, len(judged))
    return RateWithInterval(
        failures=failures,
        judged=len(judged),
        errors=errors,
        unjudged=len(outcomes) - errors - len(judged),
        rate=failures / len(judged) if judged else None,
        interval_low=interval[0] if interval else None,
        interval_high=interval[1] if interval else None,
    )


class Observation(BaseModel):
    """What was seen on one world, apart from the label that summarizes it."""

    model_config = ConfigDict(extra="forbid")

    world: RateWithInterval
    baseline: RateWithInterval | None = None
    """The fresh baseline runs made for this world's pairs, or None when none were made."""
    note: str = (
        "counts of judged runs on this world; an observation, not a statement that the mutation "
        "raises the agent's failure probability"
    )


class Multiplicity(BaseModel):
    """What an audit that looks at many worlds must say about its per-world decisions."""

    model_config = ConfigDict(extra="forbid")

    worlds_tested: int = Field(ge=0)
    worlds_with_observed_failure: int = Field(ge=0)
    worlds_with_rate_increase: int = Field(ge=0)
    alpha: float
    decisions_corrected: bool = False
    expected_rate_increase_claims_under_no_effect: float
    """``worlds_tested * alpha``: a nominal upper bound on the expected number of false
    rate-increase claims if no mutation had any effect. It is not a measured rate and not a
    family-wise guarantee: each world's test is not corrected for the number of worlds."""
    expected_worlds_with_observed_failure_under_no_effect: float | None = None
    """If every world fails at the baseline's observed rate: the expected number of worlds in which
    at least one judged run fails. None when no baseline run was judged."""
    note: str


def multiplicity_of(
    results: list[tuple[list[RunOutcome], EvidenceGrade | None]],
    baseline: list[RunOutcome],
    alpha: float = ALPHA,
) -> Multiplicity:
    """The multiplicity statement for the worlds that were tested (those with a judged run).

    ``results`` holds each world's outcomes and its grade (None when it had no failure).
    """
    tested = [(o, g) for o, g in results if any(is_judged(x) for x in o)]
    base = rate_with_interval(baseline)
    expected_observed: float | None = None
    if base.judged and base.rate is not None:
        expected_observed = round(
            sum(1 - (1 - base.rate) ** sum(is_judged(x) for x in o) for o, _ in tested), 3
        )
    n = len(tested)
    return Multiplicity(
        worlds_tested=n,
        worlds_with_observed_failure=sum(any(is_bad(x) for x in o) for o, _ in tested),
        worlds_with_rate_increase=sum(g is EvidenceGrade.RATE_INCREASE for _, g in tested),
        alpha=alpha,
        expected_rate_increase_claims_under_no_effect=round(n * alpha, 3),
        expected_worlds_with_observed_failure_under_no_effect=expected_observed,
        note=(
            f"{n} worlds were tested. Each world's paired test is not corrected for the number of "
            "worlds, and the audit as a whole has no family-wise error guarantee. If no mutation "
            f"had any effect, the expected number of false rate-increase claims is at most "
            f"{n * alpha:.2f} (worlds tested x the nominal level {alpha}: a nominal upper bound, "
            "not a measured rate), and observed failures would still appear in some worlds "
            "wherever the agent fails at random. Intervals are descriptive."
        ),
    )


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


def is_judged(outcome: RunOutcome) -> bool:
    """A run that can enter a pair: it ended without a subject error and was judged."""
    return not outcome.error and (
        outcome.violated or outcome.outcome in (Outcome.MET, Outcome.NOT_MET)
    )


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


def grade_of(test: PairedSprt | None) -> EvidenceGrade:
    """The grade of a finding: a rate increase only when the sequential test decided one."""
    if test is not None and test.decision is Decision.RATE_INCREASE:
        return EvidenceGrade.RATE_INCREASE
    return EvidenceGrade.OBSERVED_FAILURE


def observation_of(
    world: list[RunOutcome], baseline: list[RunOutcome] | None = None
) -> Observation:
    return Observation(
        world=rate_with_interval(world),
        baseline=rate_with_interval(baseline) if baseline else None,
    )


def stability_counts_only(
    baseline: list[RunOutcome] | None, world: list[RunOutcome], k: int
) -> Stability:
    """Stability for a world with no sequential test: counts, and never a rate claim.

    The runs of a world and the baseline runs made before the search are not pairs, so a
    comparison by run index would make a claim no paired test made.
    """
    value = stability(baseline, world, k)
    note = "no sequential test was run on this world: counts only, no rate claim"
    if value.note.startswith("the baseline itself is flaky"):
        note = "the baseline itself is flaky, which weakens any finding. " + note
    return value.model_copy(update={"rate_claim": None, "note": note})


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

    def can_run_after_search(self) -> bool:
        """Whether one more run fits the money, time and run limits.

        The attempts limit bounds the search for worlds. It does not stop the runs that follow the
        search (minimization and confirmation), so it is not part of this check. A refusal records
        the limit that refused it, not an earlier one (an attempts limit that ended the search).
        """
        if self.money is not None and self.spent_money >= self.money:
            self.exhausted = "money"
        elif self.seconds is not None and self.elapsed() >= self.seconds:
            self.exhausted = "seconds"
        elif self.runs is not None and self.spent_runs >= self.runs:
            self.exhausted = "runs"
        else:
            return True
        return False

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


T = TypeVar("T")
R = TypeVar("R")
T_contra = TypeVar("T_contra", contravariant=True)
R_co = TypeVar("R_co", covariant=True)


def derive_seed(base_seed: int, call: int) -> int:
    """The seed of call number ``call`` (from 0) of an audit with ``base_seed``.

    One call index runs through the whole audit (baseline, search, minimization, confirmation), so
    no seed is reused: two repeats of one world, or of one minimization step, differ.
    """
    digest = hashlib.sha256(f"{base_seed}:{call}".encode()).hexdigest()
    return int(digest[:8], 16)


class Executes(Protocol[T_contra, R_co]):
    """A subject: something that runs on a target (a world, a state) with a seed."""

    def execute(self, target: T_contra, seed: int, /) -> R_co: ...


@dataclass(frozen=True)
class Executed(Generic[R]):
    """One run that happened: its place in the audit, its seed, its result and how it was judged."""

    call: int
    seed: int
    value: R
    outcome: RunOutcome


@dataclass
class PairedRuns(Generic[R]):
    """The runs behind one sequential comparison of a world with the baseline."""

    test: PairedSprt
    world: list[Executed[R]] = field(default_factory=list)
    baseline: list[Executed[R]] = field(default_factory=list)
    stopped: Literal["decided", "max_pairs", "budget", "unpairable"] = "max_pairs"
    """Why the loop ended: the test decided, the pair limit was reached, the budget was spent, or
    two attempts in a row to form a pair failed (``unpairable``)."""

    @property
    def world_outcomes(self) -> list[RunOutcome]:
        return [e.outcome for e in self.world]

    @property
    def baseline_outcomes(self) -> list[RunOutcome]:
        return [e.outcome for e in self.baseline]


MAX_FAILED_PAIRINGS_IN_A_ROW = 2
"""Consecutive failed attempts to form a pair after which `run_paired` gives a world up."""


@dataclass
class StagedRuns(Generic[R]):
    """A world's runs in two stages: ``k`` runs, then paired runs when one of them failed."""

    screening: list[Executed[R]]
    paired: PairedRuns[R] | None = None
    """None when no screening run failed: no pair was spent on the world."""

    @property
    def test(self) -> PairedSprt | None:
        return self.paired.test if self.paired else None

    @property
    def baseline_outcomes(self) -> list[RunOutcome]:
        return self.paired.baseline_outcomes if self.paired else []


class SubjectRunner(Generic[T, R]):
    """The only place an audit executes a subject.

    Every call checks the budget first, takes a seed derived from the audit's base seed and the
    call's index, is judged, is counted, and has its cost recorded whether or not it errored. A pack
    that needs a run goes through ``run``, ``run_repeated`` or ``run_paired``; none of them returns
    a run the budget did not allow.

    ``judge(target, value, tag)`` turns what the subject returned into a `RunOutcome`. It is also
    where a pack records the run (it is called once per run, in order). ``tag`` says why the run was
    made (``"search"``, ``"baseline"``, ``"minimize"``, ``"confirm"``, ...).
    """

    def __init__(
        self,
        subject: Executes[T, R],
        judge: Callable[[T, R, str], RunOutcome],
        budget: Budget,
        *,
        seed: int = 0,
    ) -> None:
        self.subject = subject
        self.judge = judge
        self.budget = budget
        self.seed = seed
        self.calls = 0
        """Subject calls made so far. Equals ``budget.spent_runs`` when the budget is not shared."""

    def run(self, target: T, tag: str = "", *, after_search: bool = False) -> Executed[R] | None:
        """One run, or None when the budget does not allow it.

        ``after_search`` leaves the attempts limit out of the check: it bounds the search for
        worlds, not the runs that follow it (baseline repeats, minimization, confirmation).
        """
        allowed = self.budget.can_run_after_search() if after_search else self.budget.can_run()
        if not allowed:
            return None
        call = self.calls
        self.calls += 1
        seed = derive_seed(self.seed, call)
        value = self.subject.execute(target, seed)
        outcome = self.judge(target, value, tag)
        self.budget.record_run(outcome.cost)
        return Executed(call, seed, value, outcome)

    def run_repeated(
        self, target: T, k: int, tag: str = "", *, after_search: bool = False
    ) -> list[Executed[R]]:
        """Up to ``k`` runs of one target, fewer when the budget ends first."""
        done: list[Executed[R]] = []
        for _ in range(k):
            executed = self.run(target, tag, after_search=after_search)
            if executed is None:
                break
            done.append(executed)
        return done

    def run_staged(
        self,
        world: T,
        baseline: T,
        config: SprtConfig,
        k: int,
        tag: str = "search",
        *,
        after_search: bool = False,
    ) -> StagedRuns[R]:
        """``k`` runs of a world; fresh pairs with the baseline only if one of them failed.

        A world that never failed has no failure to test, so no baseline run is spent on it. The
        pairs are new runs: the screening runs choose which worlds are tested and take no part in
        the test, so choosing on a failure does not bias it. ``after_search`` is as for `run`.
        """
        screening = self.run_repeated(world, k, tag, after_search=after_search)
        if not any(is_bad(e.outcome) for e in screening):
            return StagedRuns(screening)
        return StagedRuns(
            screening,
            self.run_paired(world, baseline, config, tag, after_search=after_search),
        )

    def run_paired(
        self,
        world: T,
        baseline: T,
        config: SprtConfig,
        tag: str = "search",
        *,
        after_search: bool = False,
    ) -> PairedRuns[R]:
        """Pairs of a ``world`` run and a *fresh* ``baseline`` run, until the test decides.

        A baseline run is made for every pair: no baseline outcome is reused or assumed. A run that
        errored or could not be judged forms no pair (it stays in the run lists and is counted in
        the test's record). The loop gives up when two runs in a row form no pair, so an agent that
        fails on every run of a world costs a few runs, not the whole pair limit. The world run is
        made first, and the baseline run only when it can form a pair.
        """
        test = PairedSprt(config)
        paired: PairedRuns[R] = PairedRuns(test)
        errored = unjudged = failed_in_a_row = 0

        def usable(executed: Executed[R]) -> bool:
            nonlocal errored, unjudged
            if executed.outcome.error:
                errored += 1
            elif not is_judged(executed.outcome):
                unjudged += 1
            else:
                return True
            return False

        paired.stopped = "max_pairs"
        while test.pairs < config.max_pairs:
            made = self.run(world, tag, after_search=after_search)
            if made is None:
                paired.stopped = "budget"
                break
            paired.world.append(made)
            fresh: Executed[R] | None = None
            ok = usable(made)
            if ok:
                fresh = self.run(baseline, tag, after_search=after_search)
                if fresh is None:
                    paired.stopped = "budget"
                    break
                paired.baseline.append(fresh)
                ok = usable(fresh)
            if not ok:
                failed_in_a_row += 1
                if failed_in_a_row >= MAX_FAILED_PAIRINGS_IN_A_ROW:
                    paired.stopped = "unpairable"
                    break
                continue
            failed_in_a_row = 0
            assert fresh is not None
            if test.add(is_bad(fresh.outcome), is_bad(made.outcome)) is not Decision.CONTINUE:
                paired.stopped = "decided"
                break
        test.pairing = PairingInfo(len(paired.world), len(paired.baseline), errored, unjudged)
        return paired
