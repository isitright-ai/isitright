"""H2: a pair is two runs that happened; the sequential test stops when the real baselines run out.

0.8.0 paired runs 5 to 16 of the research pack against a baseline that was never run and was
assumed to pass, and the data pack reused its 3 baseline outcomes in a cycle. With equal failure
rates in both worlds both rules claimed a rate increase far more often than the 5% the test
promises (research: 6% at a 30% failure rate, 27% at 50%).

The statistical tests drive the research pack's own ``_paired`` method with a scripted subject.
They do not run 2,000 full audits per rate (each starts a host process and generates worlds): the
data pack's loop is covered by a smaller end-to-end test of ``run_live`` and by the shared helper.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import pytest

from isitright.core.oracles import Outcome
from isitright.core.sequential import Decision
from isitright.core.stochastic import Budget, RunOutcome
from isitright.packs.research.audit import WorldResult

from .research_fixtures import audit

AUDITS = 2000
SIGNIFICANCE = 0.05
MARGIN = 3 * (SIGNIFICANCE * (1 - SIGNIFICANCE) / AUDITS) ** 0.5


def _outcome(bad: bool) -> RunOutcome:
    return RunOutcome(Outcome.NOT_MET if bad else Outcome.MET)


def _paired_decision(
    rng: random.Random,
    *,
    baseline_rate: float,
    world_rate: float,
    baselines: int = 4,
    max_pairs: int = 16,
    world_runs: list[int] | None = None,
    make_outcome: Callable[[random.Random, float], RunOutcome] | None = None,
    baseline_outcomes: list[RunOutcome] | None = None,
) -> WorldResult:
    """One research ``_paired`` call with a scripted subject (the pack's real loop)."""
    a = audit(max_pairs=max_pairs)
    make = make_outcome or (lambda r, p: _outcome(r.random() < p))
    base = baseline_outcomes or [make(rng, baseline_rate) for _ in range(baselines)]
    calls: list[int] = world_runs if world_runs is not None else []

    def scripted_trial(*_: Any) -> Callable[[int], RunOutcome]:
        def run_trial(index: int) -> RunOutcome:
            calls.append(index)
            return make(rng, world_rate)

        return run_trial

    a._trial = scripted_trial  # type: ignore[method-assign,assignment]
    result = WorldResult(a.base, a.base_validity)
    a._paired(None, a.base, None, base, None, result, Budget())  # type: ignore[arg-type]
    return result


@pytest.mark.parametrize("rate", [0.3, 0.5])
def test_equal_failure_rates_rarely_give_a_rate_increase_in_research(rate: float) -> None:
    rng = random.Random(20261116)
    claims = sum(
        _paired_decision(rng, baseline_rate=rate, world_rate=rate).sequential.decision  # type: ignore[union-attr]
        is Decision.RATE_INCREASE
        for _ in range(AUDITS)
    )
    assert claims / AUDITS <= SIGNIFICANCE + MARGIN, f"{claims} of {AUDITS} audits claimed it"


def test_research_never_runs_more_world_runs_than_it_has_baseline_runs() -> None:
    rng = random.Random(1)
    calls: list[int] = []
    result = _paired_decision(rng, baseline_rate=0.5, world_rate=0.5, baselines=4, world_runs=calls)
    assert calls == [0, 1, 2, 3][: len(calls)] and len(calls) <= 4
    assert result.sequential is not None and result.sequential.pairs <= 4


def test_research_pairs_every_run_with_the_baseline_run_of_the_same_index() -> None:
    """The world fails on every run, the baseline on none: all 4 pairs are discordant."""
    rng = random.Random(2)
    result = _paired_decision(
        rng,
        baseline_rate=0.0,
        world_rate=1.0,
        baselines=4,
        make_outcome=lambda r, p: _outcome(p > 0.5),
    )
    test = result.sequential
    assert test is not None
    assert (test.pairs, test.world_only, test.baseline_only) == (4, 4, 0)
    # four pairs cannot reach the boundary; running out of baseline runs ends the test
    assert test.decision is Decision.UNDECIDED


def test_enough_real_pairs_can_still_show_a_rate_increase() -> None:
    rng = random.Random(3)
    result = _paired_decision(
        rng,
        baseline_rate=0.0,
        world_rate=1.0,
        baselines=12,
        make_outcome=lambda r, p: _outcome(p > 0.5),
    )
    assert result.sequential is not None
    assert result.sequential.decision is Decision.RATE_INCREASE
    assert result.sequential.pairs == 7  # 7 discordant pairs cross log(1/0.05) at effect 0.8


def test_errored_and_unjudged_runs_are_left_out_of_a_pair_and_counted() -> None:
    rng = random.Random(4)
    cannot = RunOutcome(Outcome.CANNOT_JUDGE)
    errored = RunOutcome(None, error=True)
    baseline = [_outcome(False), cannot, _outcome(False), _outcome(False), _outcome(False)]
    outcomes = iter([errored, _outcome(True), cannot, _outcome(True), _outcome(True)])
    result = _paired_decision(
        rng,
        baseline_rate=0.0,
        world_rate=1.0,
        baseline_outcomes=baseline,
        make_outcome=lambda r, p: next(outcomes),
    )
    test = result.sequential
    assert test is not None
    # pair 0: world run errored; pair 1: baseline run unjudged; pair 2: world run unjudged
    assert test.pairs == 2 and test.world_only == 2
    assert len(result.outcomes) == 5  # all five runs happened and are kept in the counts
    assert "5 baseline run(s)" in test.record().note
    assert "2 pair(s)" in test.record().note


def test_the_report_says_how_many_pairs_the_comparison_rests_on() -> None:
    rng = random.Random(5)
    result = _paired_decision(rng, baseline_rate=0.5, world_rate=0.5, baselines=4)
    note = result.sequential.record().note  # type: ignore[union-attr]
    assert "baseline run(s) that were made" in note and "pair(s)" in note


# -- end to end, research --------------------------------------------------------------------


class _Stochastic:
    """The credulous stand-in, declared stochastic so the audit runs its sequential path."""

    stochastic = True

    def __init__(self) -> None:
        from isitright.packs.research.agents import STAND_INS

        from .research_fixtures import task

        self.inner = STAND_INS["credulous"](task())
        self.label = self.inner.label

    def run(self, tools: Any, task: Any, seed: int) -> Any:
        return self.inner.run(tools, task, seed)


def test_a_stochastic_research_audit_has_no_case_level_stability_that_pools_worlds() -> None:
    a = audit(depth=1, runs=3)
    report = a.check(a.stand_in(_Stochastic()))  # type: ignore[arg-type]
    assert report.stability is None
    for finding in report.findings:
        assert finding.stability is not None
        assert finding.stability.sequential is not None
        assert finding.stability.sequential.pairs <= 3  # the baseline ran 3 times


# -- end to end, data ------------------------------------------------------------------------

pandas = pytest.importorskip("pandas")


def test_the_data_pack_never_runs_more_world_runs_than_it_has_baseline_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from isitright.packs.data.audit import AuditConfig, DataAudit
    from isitright.packs.data.live import LiveConfig, run_live
    from isitright.packs.data.task import load_task
    from tests.data_agents import FixedProgramAgent
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    task = load_task(make_task(tmp_path_factory.mktemp("pairing")))
    with DataAudit(
        task, AuditConfig(attempts=60, trust_code=True, reuse=30, timeout_seconds=20.0)
    ) as data_audit:
        recorded = program(DROPNA_FORGOTTEN, "baseline")
        agent = FixedProgramAgent(data_audit.host, DROPNA_FORGOTTEN)
        case = run_live(
            data_audit,
            agent,
            program=recorded,
            config=LiveConfig(
                baseline_runs=2,
                max_trials=8,
                attempts=40,
                max_worlds=6,
                verify_minimized_runs=0,
            ),
        )
    live = [f for f in case.findings if f.live is not None]
    assert live, "the scripted agent fails on changed worlds, so there are findings"
    for finding in live:
        assert finding.live is not None and finding.live.runs <= 2, finding.live
        assert finding.stability is not None and finding.stability.sequential is not None
        assert finding.stability.sequential.pairs <= 2
        # the baseline runs ran out, which ends the test instead of leaving it open
        assert finding.stability.sequential.decision is not Decision.CONTINUE
        assert "baseline run(s) that were made" in finding.stability.sequential.note
