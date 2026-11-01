"""A baseline run that did not complete is skipped when pairing, not the end of the world's runs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from isitright.core.oracles import Outcome
from isitright.core.sequential import Decision, SprtConfig
from isitright.core.stochastic import Budget, RunOutcome
from isitright.packs.mcp.audit import _run_world

OK = RunOutcome(Outcome.MET)
BAD = RunOutcome(Outcome.NOT_MET)
ERROR = RunOutcome(None, error=True)


def _scripted(outcomes: list[RunOutcome]) -> Any:
    queue = iter(outcomes)
    return lambda _rw, _result, _trial: next(queue)


def test_a_failed_baseline_run_is_skipped_and_the_test_still_decides() -> None:
    world = SimpleNamespace(id="w")
    base_world = SimpleNamespace(id="baseline")
    base = SimpleNamespace(world=base_world, outcomes=[ERROR, OK, OK], runs=[])
    result = SimpleNamespace(outcomes=[], runs=[], sequential=None)
    runs = {"w": _scripted([BAD] * 20), "baseline": _scripted([OK] * 20)}

    def run_trial(rw: Any, target: Any, trial: int) -> RunOutcome:
        return runs[rw.id](rw, target, trial)

    _run_world(world, result, base, run_trial, Budget(), SprtConfig(), 4, True)  # type: ignore[arg-type]
    assert result.sequential is not None and result.sequential.decision is Decision.RATE_INCREASE
    assert result.sequential.pairs >= 4
    assert len(base.outcomes) > 3  # extra baseline runs were made to pair with


def test_a_baseline_that_keeps_failing_ends_the_world_with_counts_only() -> None:
    world = SimpleNamespace(id="w")
    base = SimpleNamespace(world=SimpleNamespace(id="baseline"), outcomes=[OK, ERROR], runs=[])
    result = SimpleNamespace(outcomes=[], runs=[], sequential=None)
    runs = {"w": _scripted([BAD] * 20), "baseline": _scripted([ERROR] * 20)}

    def run_trial(rw: Any, target: Any, trial: int) -> RunOutcome:
        return runs[rw.id](rw, target, trial)

    _run_world(world, result, base, run_trial, Budget(), SprtConfig(), 4, True)  # type: ignore[arg-type]
    assert result.sequential is not None and result.sequential.decision is Decision.CONTINUE
    assert result.sequential.pairs == 1
