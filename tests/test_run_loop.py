"""N1: one run loop in the core (`SubjectRunner`).

The loop checks the budget before every call, records the cost of every run (errored ones
included), counts calls, derives a distinct seed for each call and pairs every world run with a
fresh baseline run. The tests drive it with scripted subjects. The packs' own audit paths are
covered in ``test_run_loop_packs.py``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

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


# -- budget, cost, counter -----------------------------------------------------------------------


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


# -- seeds ---------------------------------------------------------------------------------------


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


# -- pairing -------------------------------------------------------------------------------------


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
    assert paired.stopped == "unpairable" and len(subject.calls) == 2
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


# -- the statistics, through the shared loop -----------------------------------------------------


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


# -- what counts as a failed pairing attempt -----------------------------------------------------


def _paired(
    world: list[RunOutcome], base: list[RunOutcome], budget: Budget | None = None
) -> tuple[Scripted, Any]:
    subject = Scripted({"w": world, "base": base})
    paired = runner_for(subject, budget).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16)
    )
    return subject, paired


def test_two_unusable_world_runs_in_a_row_give_the_world_up_with_no_baseline_run() -> None:
    subject, paired = _paired([ERROR, UNJUDGED] + [BAD] * 20, [OK] * 20)
    names = [name for name, _ in subject.calls]
    assert names == ["w", "w"], "a baseline run is made only for a usable world run"
    assert paired.stopped == "unpairable" and paired.test.pairs == 0
    record = paired.test.record()
    assert (record.world_runs, record.baseline_runs) == (2, 0)
    assert (record.excluded_errored, record.excluded_unjudged) == (1, 1)
    assert paired.test.decision is Decision.CONTINUE


def test_two_unusable_baseline_runs_in_a_row_give_the_world_up_though_world_runs_are_usable() -> (
    None
):
    """Each failed attempt is a usable world run met by an unusable baseline run. The rule counts
    failed attempts to form a pair, not unusable executions: it stops after the second."""
    subject, paired = _paired([BAD] * 20, [ERROR, UNJUDGED] + [OK] * 20)
    assert [name for name, _ in subject.calls] == ["w", "base", "w", "base"]
    assert paired.stopped == "unpairable" and paired.test.pairs == 0
    record = paired.test.record()
    assert (record.world_runs, record.baseline_runs) == (2, 2)
    assert (record.excluded_errored, record.excluded_unjudged) == (1, 1)


def test_a_valid_pair_resets_the_count_of_failed_pairing_attempts() -> None:
    """fail, pair, fail, pair, fail, pair...: never two failures in a row, so the loop goes on."""
    world = [BAD] * 20
    base = [ERROR, OK, ERROR, OK, ERROR, OK, ERROR, OK, ERROR, OK, ERROR, OK, ERROR, OK, OK, OK]
    _subject, paired = _paired(world, base)
    record = paired.test.record()
    assert paired.stopped == "decided" and paired.test.decision is Decision.RATE_INCREASE
    assert paired.test.pairs == 7, "seven valid pairs cross the boundary"
    assert record.excluded_errored == 7 and record.excluded_unjudged == 0
    assert (record.world_runs, record.baseline_runs) == (14, 14)


def test_failed_attempts_that_are_not_consecutive_never_stop_the_loop_at_the_pair_limit() -> None:
    world = [BAD, OK] * 40
    base = [ERROR, OK] * 40
    _subject, paired = _paired(world, base)
    assert paired.stopped in {"decided", "max_pairs"}
    assert paired.test.pairs >= 1


# -- the budget refuses between the two runs of a pair -------------------------------------------


def test_a_money_budget_refusing_the_baseline_run_keeps_the_world_run_and_forms_no_pair() -> None:
    paid = RunOutcome(Outcome.NOT_MET, cost=Cost(money=1.0))
    subject = Scripted(
        {"w": [paid] * 5, "base": [RunOutcome(Outcome.MET, cost=Cost(money=1.0))] * 5}
    )
    budget = Budget(money=1.0)
    paired = runner_for(subject, budget).run_paired(
        Target("w"), Target("base"), SprtConfig(min_pairs=4, max_pairs=16)
    )
    assert [name for name, _ in subject.calls] == ["w"], "the baseline run was never executed"
    assert paired.stopped == "budget" and paired.test.pairs == 0
    assert len(paired.world) == 1 and paired.baseline == []
    assert paired.test.decision is Decision.CONTINUE
    assert budget.spent_runs == 1 and budget.exhausted == "money"
    record = paired.test.record()
    assert (record.world_runs, record.baseline_runs) == (1, 0)


# -- the reason a budget stopped -----------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _budget_with_clock(monkeypatch: pytest.MonkeyPatch, **limits: Any) -> tuple[Budget, Clock]:
    clock = Clock()
    monkeypatch.setattr("isitright.core.stochastic.time.monotonic", clock)
    return Budget(**limits), clock


def test_after_the_search_the_stop_reason_is_the_limit_that_refused_not_the_attempts_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, clock = _budget_with_clock(monkeypatch, attempts=1, seconds=10.0, runs=5)
    budget.attempt()
    assert budget.can_attempt() is False and budget.exhausted == "attempts"
    assert budget.can_run_after_search() is True, "the attempts limit does not stop later runs"
    clock.now += 11.0
    assert budget.can_run_after_search() is False
    assert budget.exhausted == "seconds"
    assert budget.to_json()["stopped_by"] == "seconds"


def test_after_the_search_a_spent_run_limit_is_reported_as_runs() -> None:
    budget = Budget(attempts=1, runs=2)
    budget.attempt()
    assert budget.can_attempt() is False and budget.exhausted == "attempts"
    runner = runner_for(Scripted({"w": [OK] * 5}), budget)
    assert len(runner.run_repeated(Target("w"), 5, after_search=True)) == 2
    assert budget.exhausted == "runs" and budget.to_json()["stopped_by"] == "runs"


def test_after_the_search_a_spent_money_limit_is_reported_as_money() -> None:
    budget = Budget(attempts=1, money=1.0, runs=10)
    budget.attempt()
    assert budget.can_attempt() is False
    paid = RunOutcome(Outcome.MET, cost=Cost(money=1.0))
    runner = runner_for(Scripted({"w": [paid] * 5}), budget)
    assert len(runner.run_repeated(Target("w"), 5, after_search=True)) == 1
    assert budget.exhausted == "money"


def test_a_refused_run_after_the_search_does_not_execute_or_consume_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget, clock = _budget_with_clock(monkeypatch, seconds=5.0)
    subject = Scripted({"w": [OK] * 5})
    runner = runner_for(subject, budget)
    assert runner.run(Target("w"), after_search=True) is not None
    clock.now += 6.0
    assert runner.run(Target("w"), after_search=True) is None
    assert len(subject.calls) == 1 and budget.spent_runs == 1


def test_during_the_search_the_attempts_limit_still_refuses_and_is_reported() -> None:
    budget = Budget(attempts=1, runs=5)
    budget.attempt()
    runner = runner_for(Scripted({"w": [OK] * 5}), budget)
    assert runner.run(Target("w")) is None
    assert budget.exhausted == "attempts"
