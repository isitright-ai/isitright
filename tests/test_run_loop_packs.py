# Proposed fixture: pending owner review
# Scripted subjects for the null and power simulations of the shared run loop. Their failure rates
# are chosen in the tests; they model no real agent.
"""The three packs' real audit paths run through the shared loop.

Each pack is driven through its own audit entry point (research ``ResearchAudit.check``, data
``run_live``, agents ``run_scenario``) with a scripted subject that fails at a chosen rate:

* null: the same failure rate in the baseline and in the world. The share of worlds that get a
  ``RATE_INCREASE`` decision stays at or below 5% plus three standard errors of the share;
* power: 10% in the baseline against 70% in the world. The share of worlds that get the decision
  is at least 80% minus three standard errors.

The default suite runs a small number of seeded audits. ``pytest -m statistical`` runs the full
size (research and data: hundreds of audits, agents: several hundred).
"""

from __future__ import annotations

import math
import os
import random
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from isitright.core.oracles import Role
from isitright.core.sequential import Decision
from isitright.core.stochastic import Budget

SIZES = [
    pytest.param("small", id="small"),
    pytest.param("full", id="full", marks=pytest.mark.statistical),
]
NULL_RATES = [0.3, 0.5]


def _margin(share: float, n: int) -> float:
    return 3 * math.sqrt(max(share * (1 - share), 0.01) / n)


def _assert_null(claims: int, tests: int, rate: float) -> None:
    assert tests >= 20, f"too few world tests to say anything: {tests}"
    limit = 0.05 + _margin(0.05, tests)
    assert claims / tests <= limit, (
        f"{claims} of {tests} worlds got a rate increase at a {rate:.0%} failure rate in both "
        f"(limit {limit:.3f})"
    )


def _assert_power(detected: int, tests: int) -> None:
    assert tests >= 20, f"too few world tests to say anything: {tests}"
    floor = 0.80 - _margin(0.8, tests)
    assert detected / tests >= floor, f"{detected} of {tests} worlds found (floor {floor:.3f})"


def test_the_default_pair_limits_leave_room_for_a_rate_increase() -> None:
    """7 discordant pairs cross the boundary at the default test, and a rise from 10% to 70% is
    found 80% of the time only from 16 pairs on (the run loop's null and power tests): no pack
    defaults below that."""
    import inspect

    from isitright.packs.data.cli import audit_command
    from isitright.packs.data.live import LiveConfig
    from isitright.packs.mcp.audit import DEFAULT_MAX_TRIALS
    from isitright.packs.research.audit import AuditConfig

    assert DEFAULT_MAX_TRIALS >= 16
    assert AuditConfig().max_pairs >= 16
    assert LiveConfig().max_trials >= 16
    assert inspect.signature(audit_command).parameters["max_trials"].default >= 16


# -- research ----------------------------------------------------------------------------------

RESEARCH_AUDITS = {"small": 40, "full": 400}


def _flaky_research_subject(a: Any, base_rate: float, world_rate: float) -> Any:
    """The careful stand-in, with each run after the first citing a document that does not exist (a
    violated invariant in any world) with the given probability. Which runs fail depends only on
    the seed."""
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject
    from isitright.packs.research.runs import Citation, Claim

    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()
    calls = [0]

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        first, calls[0] = calls[0] == 0, calls[0] + 1
        rate = base_rate if world.fingerprint() == base else world_rate
        if not first and random.Random(seed).random() < rate:
            ghost = Claim(text="x", citations=[Citation(doc_id="no-such-document", quote="x")])
            report = run.report.model_copy(
                update={"claims": [ghost], "answer": run.report.answer or "x"}
            )
            run = run.model_copy(update={"report": report})
        return run

    return Subject(careful.label, True, execute)


def _research_decisions(
    audits: int, base_rate: float, world_rate: float, seed: int
) -> list[tuple[bool, Decision]]:
    from .research_fixtures import audit

    decisions: list[tuple[bool, Decision]] = []
    for n in range(audits):
        a = audit(
            depth=1, runs=4, allow_failing_baseline=True, minimize=False, seed=seed * 1000 + n
        )
        seen: list[tuple[str, Decision]] = []
        original = a._evaluate_live

        def spy(
            candidate: Any,
            *args: Any,
            seen: list[tuple[str, Decision]] = seen,
            original: Any = original,
        ) -> Any:
            evaluation = original(candidate, *args)
            result = args[-1][candidate.world.fingerprint()]
            if result.sequential is not None:
                seen.append((candidate.world.fingerprint(), result.sequential.decision))
            return evaluation

        a._evaluate_live = spy  # type: ignore[method-assign]
        a.check(_flaky_research_subject(a, base_rate, world_rate))
        base = a.base.fingerprint()
        decisions.extend((fp == base, d) for fp, d in seen)
    return decisions


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("rate", NULL_RATES)
def test_research_equal_failure_rates_rarely_give_a_rate_increase(size: str, rate: float) -> None:
    decisions = _research_decisions(RESEARCH_AUDITS[size], rate, rate, seed=1)
    claims = sum(d is Decision.RATE_INCREASE for _, d in decisions)
    _assert_null(claims, len(decisions), rate)


@pytest.mark.parametrize("size", SIZES)
def test_research_ten_against_seventy_percent_is_found(size: str) -> None:
    decisions = _research_decisions(RESEARCH_AUDITS[size], 0.10, 0.70, seed=2)
    worlds = [d for is_base, d in decisions if not is_base]
    _assert_power(sum(d is Decision.RATE_INCREASE for d in worlds), len(worlds))


def test_research_never_reuses_a_seed_across_search_minimization_and_confirmation() -> None:
    """Minimization used to run every candidate with the same seed."""
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject

    from .research_fixtures import audit

    a = audit(depth=1, runs=3, minimize=True)
    inner = a.stand_in(STAND_INS["credulous"](a.task))
    seeds: list[int] = []

    def execute(world: Any, seed: int) -> Any:
        seeds.append(seed)
        return inner.execute(world, seed)

    report = a.check(Subject(inner.label, True, execute))
    assert any(f.minimization.get("minimized") for f in report.findings)
    assert len(seeds) > 30 and len(set(seeds)) == len(seeds)


def test_research_refuses_a_budget_that_allows_no_baseline_run() -> None:
    """0.8.1 made one baseline run whatever the budget; no run is made past a limit now."""
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import ResearchInputError

    from .research_fixtures import audit

    a = audit(max_runs=0)
    subject = a.stand_in(STAND_INS["careful"](a.task))
    with pytest.raises(ResearchInputError, match="the budget allows no run"):
        a.check(subject)


def test_research_sequential_records_say_how_the_pairs_were_made() -> None:
    from .research_fixtures import audit

    a = audit(depth=1, runs=3, allow_failing_baseline=True, minimize=False)
    report = a.check(_flaky_research_subject(a, 0.5, 0.5))
    records = [f.stability.sequential for f in report.findings if f.stability]
    assert records
    for record in records:
        assert record is not None
        assert "fresh baseline run" in record.note
        assert record.pairs <= record.baseline_runs <= record.world_runs


# -- data --------------------------------------------------------------------------------------

DATA_AUDITS = {"small": 12, "full": 150}


class _FlakyDataAgent:
    """Answers the north mean right, or with a wrong sentinel with the given probability. The
    baseline is recognized by its file; the world by anything else."""

    name = "flaky"
    model = "none"

    def __init__(self, rng: random.Random, base_rate: float, world_rate: float) -> None:
        from tests.data_agents import CsvAgent
        from tests.data_factories import ORDERS

        self.rng = rng
        self.rates = (base_rate, world_rate)
        self.inner = CsvAgent()
        self.orders = ORDERS
        self.calls = 0

    def solve(self, question: str, directory: Path) -> Any:
        from isitright.packs.data.adapters import AgentRun

        self.calls += 1
        on_base = (directory / "orders.csv").read_text(encoding="utf-8") == self.orders
        rate = self.rates[0] if on_base else self.rates[1]
        if self.rng.random() < rate:
            return AgentRun(code="# wrong", answer=-1.0, input_tokens=5, output_tokens=5)
        return self.inner.solve(question, directory)


@pytest.fixture(scope="module")
def data_audit(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    pytest.importorskip("pandas")
    from isitright.packs.data.audit import AuditConfig, DataAudit
    from isitright.packs.data.task import load_task

    from .data_factories import make_task

    task = load_task(make_task(tmp_path_factory.mktemp("run-loop-data")))
    with DataAudit(
        task, AuditConfig(attempts=60, trust_code=True, reuse=30, timeout_seconds=20.0)
    ) as value:
        yield value


def _data_decisions(
    audit: Any, audits: int, base_rate: float, world_rate: float, seed: int, max_trials: int = 16
) -> tuple[list[Decision], int]:
    from isitright.packs.data.live import LiveConfig, run_live

    decisions: list[Decision] = []
    world_tests = 0
    for n in range(audits):
        agent = _FlakyDataAgent(random.Random(seed * 1000 + n), base_rate, world_rate)
        case = run_live(
            audit,
            agent,
            config=LiveConfig(
                baseline_runs=3,
                max_trials=max_trials,
                attempts=40,
                max_worlds=6,
                verify_minimized_runs=0,
                seed=seed * 1000 + n,
            ),
        )
        world_tests += sum(
            1
            for w in case.worlds
            if w.run_status != "NOT_RUN" and w.counts and w.counts["n"] > 0 and w.id != "baseline"
        )
        decisions.extend(
            f.stability.sequential.decision
            for f in case.findings
            if f.stability is not None and f.stability.sequential is not None
        )
    return decisions, world_tests


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("rate", NULL_RATES)
def test_data_equal_failure_rates_rarely_give_a_rate_increase(
    data_audit: Any, size: str, rate: float
) -> None:
    decisions, world_tests = _data_decisions(data_audit, DATA_AUDITS[size], rate, rate, seed=3)
    _assert_null(sum(d is Decision.RATE_INCREASE for d in decisions), world_tests, rate)


@pytest.mark.parametrize("size", SIZES)
def test_data_with_a_long_pair_limit_still_holds_the_error_rate(data_audit: Any, size: str) -> None:
    """0.8.0 reused its 3 baseline outcomes in a cycle: 13% false claims at a 20% failure rate
    once ``--max-trials`` was 30."""
    decisions, world_tests = _data_decisions(
        data_audit, {"small": 30, "full": 150}[size], 0.2, 0.2, seed=9, max_trials=30
    )
    _assert_null(sum(d is Decision.RATE_INCREASE for d in decisions), world_tests, 0.2)


@pytest.mark.parametrize("size", SIZES)
def test_data_ten_against_seventy_percent_is_found(data_audit: Any, size: str) -> None:
    decisions, world_tests = _data_decisions(data_audit, DATA_AUDITS[size], 0.10, 0.70, seed=4)
    _assert_power(sum(d is Decision.RATE_INCREASE for d in decisions), world_tests)


def test_data_runs_the_agent_exactly_as_often_as_the_budget_says(data_audit: Any) -> None:
    from isitright.packs.data.live import LiveConfig, run_live

    agent = _FlakyDataAgent(random.Random(5), 0.3, 0.6)
    budget = Budget(runs=25)
    run_live(
        data_audit,
        agent,
        config=LiveConfig(baseline_runs=3, attempts=40, max_worlds=6, verify_minimized_runs=2),
        budget=budget,
    )
    assert agent.calls == budget.spent_runs == 25 and budget.exhausted == "runs"


def test_data_never_reuses_a_baseline_outcome_across_pairs(data_audit: Any) -> None:
    from isitright.packs.data.live import LiveConfig, run_live

    agent = _FlakyDataAgent(random.Random(6), 0.5, 0.5)
    case = run_live(
        data_audit,
        agent,
        config=LiveConfig(baseline_runs=3, attempts=40, max_worlds=4, verify_minimized_runs=0),
    )
    sequential = [
        f.stability.sequential for f in case.findings if f.stability and f.stability.sequential
    ]
    assert sequential, "a 50% agent fails somewhere"
    assert any(s.pairs > 3 for s in sequential), "more pairs than the 3 runs made before the search"
    for s in sequential:
        assert s.baseline_runs >= s.pairs
        assert "fresh baseline run" in s.note


# -- agents (MCP) ------------------------------------------------------------------------------

AGENT_AUDITS = {"small": 25, "full": 600}
SHOP = Path(__file__).parents[1] / "examples" / "agents" / "shop"
SHOP_REF = f"{SHOP / 'scenario.py'}:SCENARIO"


@pytest.fixture(scope="module")
def shop_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One real run of the oracle author's reference procedure ("good") and one of an agent that
    only lists the tools ("bad") on the baseline and on one control world, copied by the fake."""
    pytest.importorskip("mcp")
    from isitright.packs.mcp import audit as mcp_audit
    from isitright.packs.mcp.generate import generate_worlds
    from isitright.packs.mcp.model import load_scenario

    scenario = load_scenario(SHOP_REF)
    found, _ = generate_worlds(scenario, attempts=2000, depth=2)
    world = next(
        w for w in found if w.role is Role.CONTROL and w.observable and len(w.families) == 1
    )
    runs: dict[str, dict[str, Path]] = {}
    root = tmp_path_factory.mktemp("shop-artifacts")
    saved = os.environ.get("SHOP_AGENT_MODE")
    try:
        for mode, label in (("reference", "good"), ("refuse", "bad")):
            os.environ["SHOP_AGENT_MODE"] = mode
            out = root / label
            mcp_audit.run_scenario(
                scenario_ref=SHOP_REF,
                agent_command=f'"{sys.executable}" "{SHOP / "scripted_agent.py"}"',
                output_dir=out,
                k=1,
                only=[world.id],
                sequential=False,
                attempts=2000,
                trust_code=True,
                timeout_seconds=120,
            )
            runs[label] = {
                "baseline": out / "runs" / "baseline" / "1",
                world.id: out / "runs" / world.id / "1",
            }
    finally:
        if saved is None:
            os.environ.pop("SHOP_AGENT_MODE", None)
        else:
            os.environ["SHOP_AGENT_MODE"] = saved
    prepared = mcp_audit.prepare_worlds(
        scenario, "generated", attempts=2000, seed=0, only=[world.id]
    )
    return {"world": world.id, "runs": runs, "prepared": prepared}


def _fake_agent(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: dict[str, Any],
    rng: random.Random,
    base_rate: float,
    world_rate: float,
    calls: list[str],
) -> None:
    from isitright.packs.mcp import audit as mcp_audit

    def fake_run_agent(
        argv: list[str],
        run_dir: Path,
        mcp_config: Path,
        task_file: Path,
        world_id: str,
        timeout: float,
    ) -> tuple[str, int]:
        calls.append(world_id)
        rate = base_rate if world_id == "baseline" else world_rate
        source = artifacts["runs"]["bad" if rng.random() < rate else "good"][world_id]
        for name in ("state_before.json", "state_after.json", "trace.jsonl"):
            if (source / name).is_file():
                shutil.copy(source / name, run_dir / name)
        (run_dir / "agent.log").write_bytes(b"")
        return "COMPLETED", 0

    monkeypatch.setattr(mcp_audit, "run_agent", fake_run_agent)
    monkeypatch.setattr(mcp_audit, "prepare_worlds", lambda *a, **k: artifacts["prepared"])


def _agents_audit(tmp_path: Path, artifacts: dict[str, Any], n: int, **extra: Any) -> Any:
    from isitright.packs.mcp.audit import run_scenario

    return run_scenario(
        scenario_ref=SHOP_REF,
        agent_command="fake",
        output_dir=tmp_path / f"out{n}",
        k=4,
        only=[artifacts["world"]],
        attempts=2000,
        trust_code=True,
        minimize=False,
        **extra,
    )


def _agents_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifacts: dict[str, Any],
    audits: int,
    base_rate: float,
    world_rate: float,
    seed: int,
) -> list[Decision | None]:
    rng = random.Random(seed)
    out: list[Decision | None] = []
    for n in range(audits):
        _fake_agent(monkeypatch, artifacts, rng, base_rate, world_rate, [])
        report = _agents_audit(tmp_path, artifacts, n, seed=seed * 1000 + n)
        finding = next((f for f in report.cases[0].findings if f.stability), None)
        sequential = finding.stability.sequential if finding and finding.stability else None
        out.append(sequential.decision if sequential else None)
        shutil.rmtree(tmp_path / f"out{n}")
    return out


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("rate", NULL_RATES)
def test_agents_equal_failure_rates_rarely_give_a_rate_increase(
    size: str,
    rate: float,
    shop_artifacts: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits = AGENT_AUDITS[size]
    decisions = _agents_decisions(tmp_path, monkeypatch, shop_artifacts, audits, rate, rate, 7)
    _assert_null(sum(d is Decision.RATE_INCREASE for d in decisions), audits, rate)


@pytest.mark.parametrize("size", SIZES)
def test_agents_ten_against_seventy_percent_is_found(
    size: str,
    shop_artifacts: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits = AGENT_AUDITS[size]
    decisions = _agents_decisions(tmp_path, monkeypatch, shop_artifacts, audits, 0.1, 0.7, 8)
    _assert_power(sum(d is Decision.RATE_INCREASE for d in decisions), audits)


@pytest.mark.parametrize("limit", [9, 14, 31])
def test_agents_executes_exactly_the_runs_it_reports_and_no_more_than_the_limit(
    limit: int,
    shop_artifacts: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _fake_agent(monkeypatch, shop_artifacts, random.Random(limit), 0.4, 0.6, calls)
    budget = Budget(runs=limit)
    report = _agents_audit(tmp_path, shop_artifacts, 0, budget=budget)
    listed = len(report.cases[0].extensions["mcp"]["runs"])
    assert len(calls) == budget.spent_runs == listed
    assert len(calls) <= limit


def test_agents_runs_carry_distinct_seeds(
    shop_artifacts: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_agent(monkeypatch, shop_artifacts, random.Random(1), 0.4, 0.6, [])
    report = _agents_audit(tmp_path, shop_artifacts, 0)
    seeds = [r["seed"] for r in report.cases[0].extensions["mcp"]["runs"]]
    assert len(seeds) > 8 and len(set(seeds)) == len(seeds)
