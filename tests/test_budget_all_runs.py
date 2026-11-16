"""H3: every agent run is under the budget, in the research and agents packs.

In 0.8.0 the research pack checked ``budget.can_run()`` only for world runs. Baseline runs,
minimization runs and confirmation runs executed without a check and without recording their cost,
and an errored run recorded none. The agents pack's minimization steps checked the run count at the
start but not before each trial.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from isitright.core.oracles import Outcome
from isitright.core.stochastic import Budget, RunOutcome
from isitright.core.subjects import Cost

from .research_fixtures import audit, task


class _Stochastic:
    """The credulous stand-in, declared stochastic so baseline, search, minimization and
    confirmation all run through the budgeted paths."""

    stochastic = True

    def __init__(self) -> None:
        from isitright.packs.research.agents import STAND_INS

        self.inner = STAND_INS["credulous"](task())
        self.label = self.inner.label

    def run(self, tools: Any, t: Any, seed: int) -> Any:
        return self.inner.run(tools, t, seed)


def _counted_audit(**config: Any) -> tuple[Any, Any, list[int]]:
    a = audit(**config)
    subject = a.stand_in(_Stochastic())
    calls: list[int] = []
    original = subject.execute

    def counted(world: Any, seed: int) -> Any:
        calls.append(seed)
        return original(world, seed)

    subject.execute = counted
    return a, subject, calls


def _spent_runs(report: Any) -> int:
    return int(report.extensions["research"]["budget"]["spent"]["runs"])


@pytest.mark.parametrize("max_runs", [6, 12, 25])
def test_research_executes_exactly_the_runs_it_reports_and_no_more_than_max_runs(
    max_runs: int,
) -> None:
    a, subject, calls = _counted_audit(depth=1, runs=3, max_runs=max_runs, minimize=True)
    report = a.check(subject)
    assert len(calls) <= max_runs, f"{len(calls)} subject calls for --max-runs {max_runs}"
    assert len(calls) == _spent_runs(report), "every executed run is recorded in the budget"


def test_research_minimization_and_confirmation_are_run_under_the_budget() -> None:
    """With a budget big enough for the baseline and the search but not for what follows, the
    findings are still reported on the world that was run, and nothing runs past the limit."""
    a, subject, calls = _counted_audit(depth=1, runs=3, max_runs=9, minimize=True)
    report = a.check(subject)
    assert len(calls) <= 9
    for finding in report.findings:
        assert finding.divergence["reproduces_on_shown_world"] in (True, False)
        assert finding.world_id  # a verdict is always reported on a world that was run


def test_a_budget_without_room_for_the_baseline_still_makes_one_baseline_run() -> None:
    a, subject, calls = _counted_audit(depth=1, runs=3, max_runs=1, minimize=True)
    a.check(subject)
    assert len(calls) == 1


def test_an_errored_run_records_its_cost() -> None:
    from isitright.packs.research.runs import RecordedRun

    a = audit()
    base_run = a.stand_in(_Stochastic()).execute(a.base, 0)
    failing = RecordedRun.model_validate(
        {**base_run.model_dump(), "status": "SUBJECT_ERROR", "cost": {"money": 0.5}}
    )
    subject = SimpleNamespace(execute=lambda world, seed: failing)
    from isitright.packs.research.audit import WorldResult

    outcome = a._trial(subject, a.base, base_run, None, WorldResult(a.base, a.base_validity), "t")(
        0
    )  # type: ignore[arg-type]
    assert outcome.error and outcome.cost.money == pytest.approx(0.5)


# -- agents pack: minimization steps ---------------------------------------------------------


def test_agents_minimization_checks_the_budget_before_every_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from isitright.packs.mcp import audit as mcp_audit

    monkeypatch.setattr(mcp_audit, "reference_outcome", lambda scenario, world: None)
    monkeypatch.setattr(mcp_audit, "World", lambda base: SimpleNamespace(path=[]))
    executed: list[int] = []

    def run_trial(step: Any, result: Any, trial: int) -> RunOutcome:
        executed.append(trial)
        return RunOutcome(Outcome.NOT_MET, cost=Cost(money=1.0))

    def many_steps(start: Any, path: list[Any], run: Any, **kwargs: Any) -> Any:
        for _ in range(20):
            run(SimpleNamespace(path=[]))
        return SimpleNamespace(runs=20)

    monkeypatch.setattr(mcp_audit, "minimize_path_noisy", many_steps)
    budget = Budget(money=3.0)
    rw = SimpleNamespace(id="w", world=SimpleNamespace(path=[]), generated=None)
    base = SimpleNamespace(outcomes=[RunOutcome(Outcome.MET)])
    mcp_audit._minimize_world(
        SimpleNamespace(base=None),
        rw,
        base,
        run_trial,
        budget,
        [],
        20,  # type: ignore[arg-type]
    )
    assert len(executed) == 3, "a money budget of 3 pays for 3 runs of cost 1, not 20"
    assert budget.spent_runs == 3
