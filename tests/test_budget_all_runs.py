"""H3: every agent run is under the budget, in the research and agents packs.

In 0.8.0 the research pack checked ``budget.can_run()`` only for world runs. Baseline runs,
minimization runs and confirmation runs executed without a check and without recording their cost,
and an errored run recorded none. The agents pack's minimization steps checked the run count at the
start but not before each trial.
"""

from __future__ import annotations

from pathlib import Path
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


@pytest.mark.parametrize("max_runs", range(4, 41))
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


# -- agents pack: minimization steps ---------------------------------------------------------


def test_agents_minimization_checks_the_budget_before_every_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from isitright.core.stochastic import SubjectRunner
    from isitright.packs.mcp import audit as mcp_audit

    monkeypatch.setattr(mcp_audit, "reference_outcome", lambda scenario, world: None)
    monkeypatch.setattr(mcp_audit, "World", lambda base: SimpleNamespace(path=[]))
    executed: list[int] = []

    class Subject:
        def execute(self, target: Any, seed: int, /) -> RunOutcome:
            executed.append(seed)
            return RunOutcome(Outcome.NOT_MET, cost=Cost(money=1.0))

    def many_steps(start: Any, path: list[Any], run: Any, **kwargs: Any) -> Any:
        for _ in range(20):
            run(SimpleNamespace(path=[]))
        return SimpleNamespace(runs=20)

    monkeypatch.setattr(mcp_audit, "minimize_path_noisy", many_steps)
    budget = Budget(money=3.0)
    runner = SubjectRunner(Subject(), lambda _t, value, _tag: value, budget)
    rw = SimpleNamespace(id="w", world=SimpleNamespace(path=[]), generated=None)
    base = SimpleNamespace(outcomes=[RunOutcome(Outcome.MET)])
    mcp_audit._minimize_world(
        SimpleNamespace(base=None),
        rw,
        base,
        runner,  # type: ignore[arg-type]
        [],
        20,
    )
    assert len(executed) == 3, "a money budget of 3 pays for 3 runs of cost 1, not 20"
    assert budget.spent_runs == 3


# -- agents pack: a real audit of the shop example with minimization on -------------------------

SHOP = Path(__file__).parents[1] / "examples" / "agents" / "shop"
SHOP_REF = f"{SHOP / 'scenario.py'}:SCENARIO"

COUNTING_AGENT = """\
import os
import runpy

with open(os.environ["COUNT_FILE"], "a", encoding="utf-8") as handle:
    handle.write("x\\n")
runpy.run_path({agent!r}, run_name="__main__")
"""


@pytest.fixture(scope="module")
def composed_trap_world() -> str:
    from isitright.core.oracles import Role
    from isitright.packs.mcp.generate import generate_worlds
    from isitright.packs.mcp.model import load_scenario

    found, _ = generate_worlds(load_scenario(SHOP_REF), attempts=2000, depth=2)
    return next(
        w for w in found if w.role is Role.TRAP and w.observable and len(w.families) == 2
    ).id


@pytest.mark.parametrize("limit", [9, 14, 25])
def test_a_real_agents_audit_runs_exactly_the_runs_it_reports_and_never_more_than_the_limit(
    limit: int, composed_trap_world: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wrapper agent counts its own invocations. With minimization on, the number of
    invocations equals the budget's spent runs and the runs listed in the report, and stays within
    the limit; a minimization that ran out of runs is reported as not minimized."""
    import sys

    from isitright.core.stochastic import Budget
    from isitright.packs.mcp.audit import run_scenario

    wrapper = tmp_path / "counting_agent.py"
    wrapper.write_text(
        COUNTING_AGENT.format(agent=str(SHOP / "scripted_agent.py")), encoding="utf-8"
    )
    counter = tmp_path / "invocations.txt"
    counter.write_text("", encoding="utf-8")
    monkeypatch.setenv("COUNT_FILE", str(counter))
    monkeypatch.setenv("SHOP_AGENT_MODE", "careless")
    budget = Budget(runs=limit)
    report = run_scenario(
        scenario_ref=SHOP_REF,
        agent_command=f'"{sys.executable}" "{wrapper}"',
        output_dir=tmp_path / "out",
        worlds="generated",
        k=2,
        only=[composed_trap_world],
        sequential=False,
        attempts=2000,
        minimize=True,
        budget=budget,
        trust_code=True,
        timeout_seconds=120,
    )
    case = report.cases[0]
    invocations = len(counter.read_text(encoding="utf-8").split())
    listed = len(case.extensions["mcp"]["runs"])
    assert invocations == budget.spent_runs == listed
    assert invocations <= limit
    (finding,) = case.findings
    record = finding.minimization
    assert record["status"] in {"MINIMIZED", "OUT_OF_RUNS"}
    if record["status"] == "OUT_OF_RUNS":
        assert record["minimal"] is False
        assert record["mutations_after"] == record["mutations_before"] == len(finding.mutation_path)
    else:
        assert record["minimal"] is True and record["mutations_after"] < record["mutations_before"]
    if limit < 20:
        assert record["status"] == "OUT_OF_RUNS"  # too few runs to finish: cut short and said so
