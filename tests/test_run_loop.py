"""N1: one run loop in the core (`SubjectRunner`).

The loop checks the budget before every call, records the cost of every run (errored ones
included), counts calls, derives a distinct seed for each call and pairs every world run with a
fresh baseline run. The tests drive it with scripted subjects. The packs' own audit paths are
covered in ``test_run_loop_packs.py``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from isitright.core.oracles import Outcome
from isitright.core.sequential import Decision, SprtConfig
from isitright.core.stochastic import (
    Budget,
    RunOutcome,
    SubjectRunner,
    derive_seed,
)
from isitright.core.subjects import Cost

OK = RunOutcome(Outcome.MET)
BAD = RunOutcome(Outcome.NOT_MET)
ERROR = RunOutcome(None, error=True)
UNJUDGED = RunOutcome(Outcome.CANNOT_JUDGE)


@dataclass
class Target:
    name: str


class Scripted:
    """A subject that returns what a script says, per target, and remembers every call."""

    def __init__(self, scripts: dict[str, list[RunOutcome]] | None = None) -> None:
        self.scripts = {k: iter(v) for k, v in (scripts or {}).items()}
        self.calls: list[tuple[str, int]] = []

    def execute(self, target: Target, seed: int, /) -> RunOutcome:
        self.calls.append((target.name, seed))
        return next(self.scripts[target.name])


def runner_for(
    subject: Scripted, budget: Budget | None = None, seed: int = 0
) -> SubjectRunner[Target, RunOutcome]:
    return SubjectRunner(subject, lambda _t, value, _tag: value, budget or Budget(), seed=seed)


# -- budget, cost, counter ---------------------------------------------------------------------


def test_the_budget_is_checked_before_every_call_not_after() -> None:
    subject = Scripted({"w": [OK] * 50})
    budget = Budget(runs=3)
    runner = runner_for(subject, budget)
    done = runner.run_repeated(Target("w"), 10)
    assert len(done) == 3 and len(subject.calls) == 3 and runner.calls == 3
    assert budget.spent_runs == 3 and budget.exhausted == "runs"
    assert runner.run(Target("w")) is None
    assert len(subject.calls) == 3, "a refused run never reaches the subject"


def test_a_money_budget_pays_for_the_runs_that_fit() -> None:
    cost = RunOutcome(Outcome.MET, cost=Cost(money=1.0))
    subject = Scripted({"w": [cost] * 20})
    budget = Budget(money=3.0)
    runner_for(subject, budget).run_repeated(Target("w"), 20)
    assert len(subject.calls) == 3 and budget.spent_runs == 3


def test_an_errored_run_records_its_cost() -> None:
    errored = RunOutcome(None, error=True, cost=Cost(money=0.5))
    budget = Budget()
    executed = runner_for(Scripted({"w": [errored]}), budget).run(Target("w"))
    assert executed is not None and executed.outcome.error
    assert budget.spent_money == pytest.approx(0.5) and budget.spent_runs == 1


def test_runs_after_the_search_ignore_the_attempts_limit_but_not_the_run_limit() -> None:
    budget = Budget(attempts=1, runs=2)
    budget.attempt()
    assert budget.can_attempt() is False
    runner = runner_for(Scripted({"w": [OK] * 5}), budget)
    assert runner.run(Target("w")) is None, "a search-phase run needs an attempt left"
    assert len(runner.run_repeated(Target("w"), 5, after_search=True)) == 2


# -- seeds -------------------------------------------------------------------------------------


def test_every_call_gets_its_own_seed_across_repeats_and_targets() -> None:
    subject = Scripted({"a": [OK] * 40, "b": [OK] * 40})
    runner = runner_for(subject, seed=7)
    runner.run_repeated(Target("a"), 20)
    runner.run_repeated(Target("b"), 20)
    runner.run_repeated(Target("a"), 20, "minimize", after_search=True)
    seeds = [seed for _, seed in subject.calls]
    assert len(set(seeds)) == len(seeds) == 60
    assert seeds == [derive_seed(7, i) for i in range(60)]


def test_a_seed_depends_on_the_base_seed_and_is_stable() -> None:
    assert derive_seed(1, 0) == derive_seed(1, 0)
    assert derive_seed(1, 0) != derive_seed(2, 0) and derive_seed(1, 0) != derive_seed(1, 1)
    assert 0 <= derive_seed(1, 0) < 2**32


# -- pairing -----------------------------------------------------------------------------------


def test_every_pair_is_a_world_run_and_a_fresh_baseline_run() -> None:
    subject = Scripted({"w": [BAD] * 30, "base": [OK] * 30})
    runner = runner_for(subject)
    paired = runner.run_paired(Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16))
    assert paired.test.decision is Decision.RATE_INCREASE and paired.stopped == "decided"
    assert len(paired.world) == len(paired.baseline) == paired.test.pairs == 7
    names = [name for name, _ in subject.calls]
    assert names == ["w", "base"] * 7, "a baseline run is made for each pair, not reused"
    assert len({seed for _, seed in subject.calls}) == 14
    record = paired.test.record()
    assert (record.world_runs, record.baseline_runs) == (7, 7)
    assert record.excluded_errored == record.excluded_unjudged == 0


def test_a_baseline_outcome_is_never_assumed_or_reused() -> None:
    """One baseline failure among passes: the failing run pairs once and is not repeated."""
    base = [BAD, OK, OK, OK, OK, OK, OK, OK]
    subject = Scripted({"w": [BAD] * 8, "base": base})
    paired = runner_for(subject).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=8, max_pairs=8)
    )
    assert [e.outcome for e in paired.baseline] == base
    assert (paired.test.world_only, paired.test.baseline_only) == (7, 0)


def test_errored_and_unjudged_runs_form_no_pair_and_are_counted() -> None:
    subject = Scripted(
        {
            "w": [ERROR, BAD, BAD, BAD, UNJUDGED] + [BAD] * 10,
            "base": [OK, UNJUDGED] + [OK] * 10,
        }
    )
    paired = runner_for(subject).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16)
    )
    record = paired.test.record()
    # world run 0 errored (no baseline run made); world run 2 met an unjudged baseline run; world
    # run 4 was unjudged (no baseline run made). Seven pairs remain, which decide the test.
    assert record.excluded_errored == 1 and record.excluded_unjudged == 2
    assert record.world_runs == len(paired.world) == 10
    assert record.baseline_runs == len(paired.baseline) == 8
    assert paired.test.pairs == 7 and paired.test.decision is Decision.RATE_INCREASE


def test_a_subject_that_never_completes_costs_two_runs_not_the_pair_limit() -> None:
    subject = Scripted({"w": [ERROR] * 40, "base": [OK] * 40})
    paired = runner_for(subject).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16)
    )
    assert paired.stopped == "unusable" and len(subject.calls) == 2
    assert paired.test.decision is Decision.CONTINUE and paired.test.pairs == 0
    assert paired.test.record().excluded_errored == 2


def test_the_loop_stops_when_the_budget_ends_between_the_two_runs_of_a_pair() -> None:
    subject = Scripted({"w": [BAD] * 10, "base": [OK] * 10})
    budget = Budget(runs=3)
    paired = runner_for(subject, budget).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16)
    )
    assert paired.stopped == "budget" and len(subject.calls) == 3
    assert len(paired.world) == 2 and len(paired.baseline) == 1
    assert paired.test.pairs == 1


# -- the statistics, through the shared loop ----------------------------------------------------


class Bernoulli:
    """Fails with a fixed probability per target, from its own random stream."""

    def __init__(self, rates: dict[str, float], rng: random.Random) -> None:
        self.rates, self.rng = rates, rng

    def execute(self, target: Target, seed: int, /) -> RunOutcome:
        return BAD if self.rng.random() < self.rates[target.name] else OK


def _share_of_rate_increases(
    base_rate: float, world_rate: float, audits: int, seed: int, config: SprtConfig
) -> float:
    rng = random.Random(seed)
    hits = 0
    for _ in range(audits):
        runner = runner_for(Bernoulli({"w": world_rate, "base": base_rate}, rng))
        paired = runner.run_paired(Target("w"), Target("base"), config)
        hits += paired.test.decision is Decision.RATE_INCREASE
    return hits / audits


@pytest.mark.parametrize("rate", [0.3, 0.5])
def test_equal_failure_rates_rarely_give_a_rate_increase(rate: float) -> None:
    share = _share_of_rate_increases(rate, rate, 3000, 11, SprtConfig(min_pairs=4, max_pairs=16))
    assert share <= 0.05, f"{share:.3f} of 3000 audits claimed a rate increase"


def test_ten_against_seventy_percent_is_found_at_least_80_percent_of_the_time() -> None:
    share = _share_of_rate_increases(0.1, 0.7, 3000, 12, SprtConfig(min_pairs=4, max_pairs=16))
    assert share >= 0.80, f"{share:.3f} of 3000 audits found it"
