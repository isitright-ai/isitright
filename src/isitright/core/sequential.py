"""Sequential tests for live agents: stop when the evidence is adequate, with the error controlled.

Two sequential probability ratio tests, both truncated at a maximum number of looks. The boundaries
are 1/alpha above and beta below on the likelihood ratio, which Ville's inequality makes exact
bounds rather than Wald's approximations: under the null the ratio is a martingale, so it reaches
1/alpha at any look with probability at most alpha, and under the alternative its inverse reaches
1/beta with probability at most beta. Truncation only removes chances to stop, so type I stays at
or below alpha.

* `PairedSprt` compares a world with the baseline on paired runs. Only discordant pairs carry
  information. Under the null (the world fails no more often than the baseline) a discordant pair
  is against the world with probability 1/2; the alternative states a larger share, `effect`. It is
  the sequential form of the exact McNemar test used for a fixed number of pairs in 0.4. Its
  anytime-valid p-value is min(1, 1 / the largest likelihood ratio seen), by Ville's inequality.
* `RateSprt` tests one failure rate against a reference rate, for minimization steps, where each
  candidate subset of a path is judged by repeated runs.

The error control is per sequence (per world, per minimization step). Across many worlds the tests
are not corrected for multiplicity: a report states counts for those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

TEST_NAME = "sequential probability ratio test on discordant pairs"


class Decision(StrEnum):
    RATE_INCREASE = "RATE_INCREASE"
    """Upper boundary crossed: the world fails more often than the baseline."""
    NO_INCREASE_AT_EFFECT = "NO_INCREASE_AT_EFFECT"
    """Lower boundary crossed: adequate evidence against an increase of the stated size."""
    UNDECIDED = "UNDECIDED"
    """The maximum number of pairs was reached between the boundaries."""
    NO_DISCORDANCE = "NO_DISCORDANCE"
    """The minimum number of pairs was reached with no pair against the world: counts only."""
    CONTINUE = "CONTINUE"


@dataclass(frozen=True)
class SprtConfig:
    alpha: float = 0.05
    beta: float = 0.2
    effect: float = 0.8
    """Alternative: the share of discordant pairs against the world."""
    min_pairs: int = 4
    max_pairs: int = 16

    def __post_init__(self) -> None:
        if not (0 < self.alpha < 1 and 0 < self.beta < 1 and 0.5 < self.effect < 1):
            raise ValueError("alpha and beta lie in (0, 1) and effect in (0.5, 1)")
        if not 1 <= self.min_pairs <= self.max_pairs:
            raise ValueError("need 1 <= min_pairs <= max_pairs")

    @property
    def upper(self) -> float:
        return math.log(1 / self.alpha)

    @property
    def lower(self) -> float:
        return math.log(self.beta)


class Look(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: int
    log_likelihood_ratio: float


class SequentialRecord(BaseModel):
    """What the report keeps of a sequential test: test, looks, boundaries, decision."""

    model_config = ConfigDict(extra="forbid")

    test: str = TEST_NAME
    alpha: float
    beta: float
    null_share: float = 0.5
    alternative_share: float
    upper_boundary: float
    lower_boundary: float
    min_pairs: int
    max_pairs: int
    pairs: int
    discordant_world_only: int
    discordant_baseline_only: int
    looks: list[Look] = Field(default_factory=list)
    log_likelihood_ratio: float
    p_value: float
    decision: Decision
    note: str = ""


class PairedSprt:
    """Feed pairs in order; ``decision`` says whether to stop."""

    def __init__(self, config: SprtConfig | None = None) -> None:
        self.config = config or SprtConfig()
        self.pairs = 0
        self.world_only = 0
        self.baseline_only = 0
        self.llr = 0.0
        self.peak = 0.0
        self.looks: list[Look] = []
        self._for = math.log(self.config.effect / 0.5)
        self._against = math.log((1 - self.config.effect) / 0.5)
        self.decision = Decision.CONTINUE

    def add(self, baseline_bad: bool, world_bad: bool) -> Decision:
        """Add one pair; returns the decision after this look."""
        if self.decision is not Decision.CONTINUE:
            return self.decision
        self.pairs += 1
        if world_bad and not baseline_bad:
            self.world_only += 1
            self.llr += self._for
        elif baseline_bad and not world_bad:
            self.baseline_only += 1
            self.llr += self._against
        self.peak = max(self.peak, self.llr)
        self.looks.append(Look(pair=self.pairs, log_likelihood_ratio=round(self.llr, 6)))
        c = self.config
        if self.llr >= c.upper:
            self.decision = Decision.RATE_INCREASE
        elif self.llr <= c.lower:
            self.decision = Decision.NO_INCREASE_AT_EFFECT
        elif self.pairs >= c.min_pairs and self.world_only == 0:
            self.decision = Decision.NO_DISCORDANCE
        elif self.pairs >= c.max_pairs:
            self.decision = Decision.UNDECIDED
        return self.decision

    @property
    def p_value(self) -> float:
        return min(1.0, math.exp(-self.peak))

    def record(self) -> SequentialRecord:
        c = self.config
        notes = {
            Decision.RATE_INCREASE: "the upper boundary was crossed: a higher failure rate than "
            "the baseline",
            Decision.NO_INCREASE_AT_EFFECT: "the lower boundary was crossed: adequate evidence "
            "against an increase as large as the stated effect; a smaller increase is not excluded",
            Decision.UNDECIDED: "the maximum number of pairs was reached between the boundaries: "
            "counts only",
            Decision.NO_DISCORDANCE: "no pair was against the world after the minimum number of "
            "pairs: counts only, no rate claim",
            Decision.CONTINUE: "stopped before a decision (a budget ended or a run did not "
            "complete): counts only",
        }
        return SequentialRecord(
            alpha=c.alpha,
            beta=c.beta,
            alternative_share=c.effect,
            upper_boundary=round(c.upper, 6),
            lower_boundary=round(c.lower, 6),
            min_pairs=c.min_pairs,
            max_pairs=c.max_pairs,
            pairs=self.pairs,
            discordant_world_only=self.world_only,
            discordant_baseline_only=self.baseline_only,
            looks=self.looks,
            log_likelihood_ratio=round(self.llr, 6),
            p_value=round(self.p_value, 6),
            decision=self.decision,
            note=notes[self.decision],
        )


class RateDecision(StrEnum):
    ABOVE = "ABOVE"
    """The failure rate exceeds the reference (reproduces)."""
    NOT_ABOVE = "NOT_ABOVE"
    UNDECIDED = "UNDECIDED"


@dataclass(frozen=True)
class RateSprtConfig:
    reference: float = 0.05
    """Failure rate with nothing perturbed (the noise floor)."""
    effect: float = 0.5
    """Failure rate the alternative states for a subset that carries the cause."""
    alpha: float = 0.001
    beta: float = 0.001
    max_runs: int = 60


class RateSprt:
    """Bernoulli SPRT of a failure rate: H0 = the reference rate, H1 = the stated effect."""

    def __init__(self, config: RateSprtConfig | None = None) -> None:
        self.config = config or RateSprtConfig()
        c = self.config
        if not 0 < c.reference < c.effect < 1:
            raise ValueError("need 0 < reference < effect < 1")
        self._bad = math.log(c.effect / c.reference)
        self._good = math.log((1 - c.effect) / (1 - c.reference))
        self.upper = math.log(1 / c.alpha)
        self.lower = math.log(c.beta)
        self.llr = 0.0
        self.runs = 0
        self.bad = 0

    def add(self, bad: bool) -> RateDecision | None:
        self.runs += 1
        self.bad += bad
        self.llr += self._bad if bad else self._good
        if self.llr >= self.upper:
            return RateDecision.ABOVE
        if self.llr <= self.lower:
            return RateDecision.NOT_ABOVE
        if self.runs >= self.config.max_runs:
            return RateDecision.UNDECIDED
        return None
