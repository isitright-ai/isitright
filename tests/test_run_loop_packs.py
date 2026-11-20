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
    """7 discordant pairs cross the boundary at the default test. A rise from 10% to 70% is found
    about 84% of the time at 16 pairs and about 91% (minimum 3 pairs) to 94% (minimum 4) at 20:
    all three packs default to 20 pairs."""
    import inspect

    from isitright.cli import agents_run_command
    from isitright.packs.data.cli import audit_command
    from isitright.packs.data.live import LiveConfig
    from isitright.packs.mcp.audit import DEFAULT_MAX_TRIALS
    from isitright.packs.research.audit import AuditConfig

    assert DEFAULT_MAX_TRIALS == 20
    assert AuditConfig().max_pairs == 20
    assert LiveConfig().max_trials == 20
    assert inspect.signature(audit_command).parameters["max_trials"].default == 20
    assert inspect.signature(agents_run_command).parameters["max_trials"].default == 20


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


def _research_audit_worlds(
    base_rate: float, world_rate: float, seed: int = 5, **config: Any
) -> tuple[Any, list[tuple[bool, Any]]]:
    """One audit through ``check`` with its report and every evaluated world's result."""
    from .research_fixtures import audit

    a = audit(**{"depth": 1, "runs": 4, "minimize": False, "seed": seed, **config})
    seen: list[tuple[str, Any]] = []
    original = a._evaluate_live

    def spy(candidate: Any, *args: Any) -> Any:
        evaluation = original(candidate, *args)
        seen.append((candidate.world.fingerprint(), args[-1][candidate.world.fingerprint()]))
        return evaluation

    a._evaluate_live = spy  # type: ignore[method-assign]
    report = a.check(_flaky_research_subject(a, base_rate, world_rate))
    base = a.base.fingerprint()
    return report, [(fp == base, result) for fp, result in seen]


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


def test_research_the_careful_stand_in_passes_every_world_and_the_injection_fails_every_run():
    """The null and power runs assume that, without the injected failure, the oracle passes the
    stand-in in every world, and that the injection fails a run in every world and in the
    baseline."""
    from isitright.core.stochastic import is_bad

    report, worlds = _research_audit_worlds(0.0, 0.0)
    assert report.findings == [] and len(worlds) >= 10
    for _, result in worlds:
        assert result.outcomes and not any(is_bad(o) for o in result.outcomes), result.world
        assert not any(o.error for o in result.outcomes)
    report, worlds = _research_audit_worlds(1.0, 1.0)
    for is_base, result in worlds:
        runs = result.outcomes[1:] if is_base else result.outcomes  # the first call is never failed
        assert runs and all(is_bad(o) for o in runs), (is_base, result.world)


def _research_subject_with_unusable_baselines(a: Any, unusable: frozenset[int]) -> Any:
    """The baseline always passes and every mutated world always fails. The fresh baseline runs
    paired with a mutated world are numbered per world (from 1); those in ``unusable`` end in a
    subject error."""
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject
    from isitright.packs.research.runs import Citation, Claim

    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()
    state = {"last": None, "numbers": {}}

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        fingerprint = world.fingerprint()
        if fingerprint != base:
            state["last"] = fingerprint
            ghost = Claim(text="x", citations=[Citation(doc_id="no-such-document", quote="x")])
            report = run.report.model_copy(
                update={"claims": [ghost], "answer": run.report.answer or "x"}
            )
            return run.model_copy(update={"report": report})
        last = state["last"]
        if last is not None:  # a fresh baseline run made for a pair with a mutated world
            number = state["numbers"][last] = state["numbers"].get(last, 0) + 1
            if number in unusable:
                return run.model_copy(update={"status": "SUBJECT_ERROR"})
        return run

    return Subject(careful.label, True, execute)


def test_research_an_incomplete_paired_test_makes_no_rate_claim():
    """Eight failing runs of a world and eight passing preliminary baseline runs would give a
    significant fixed-sample McNemar claim by index. But two baseline runs were unusable, so only
    six pairs exist, the sequential test is undecided when the budget ends, and a rate claim would
    be a claim the paired test never made."""
    from isitright.core.oracles import Outcome
    from isitright.core.sequential import Decision
    from isitright.core.stochastic import RunOutcome, rate_claim

    premise = rate_claim([RunOutcome(Outcome.MET)] * 8, [RunOutcome(Outcome.NOT_MET)] * 8)
    assert premise is not None, "the index-based comparison would claim a rate increase"

    from .research_fixtures import audit

    a = audit(depth=1, runs=8, minimize=False, max_runs=40)  # 8 more for the screening runs
    report = a.check(_research_subject_with_unusable_baselines(a, frozenset({2, 5})))
    (finding,) = report.findings
    stability = finding.stability
    assert stability.rate_claim is None, "an undecided sequential test supports no rate claim"
    sequential = stability.sequential
    assert sequential is not None and sequential.decision is Decision.CONTINUE
    assert sequential.pairs == 6
    assert (sequential.world_runs, sequential.baseline_runs) == (8, 8)
    assert (sequential.excluded_errored, sequential.excluded_unjudged) == (2, 0)
    # the 8 screening runs and the 8 runs paired with a baseline run
    assert stability.world.n == 16 and stability.world.not_met + stability.world.violated >= 16
    assert "counts only" in sequential.note or "stopped before a decision" in sequential.note


def test_research_a_finding_counts_the_baseline_runs_made_for_its_own_world():
    from .research_fixtures import audit

    a = audit(depth=1, runs=3, minimize=False)
    report = a.check(_research_subject_with_unusable_baselines(a, frozenset({2, 5})))
    findings = [
        f
        for f in report.findings
        if f.stability and f.stability.sequential and f.stability.sequential.baseline_runs >= 5
    ]
    assert findings
    for f in findings:
        stability = f.stability
        assert stability.baseline.n == stability.sequential.baseline_runs != 3
        assert stability.baseline.errors == 2, "this world's two unusable baseline runs, no others"
        assert stability.sequential.excluded_errored == 2
        assert stability.sequential.pairs <= stability.baseline.n - 2
        assert stability.world.n == stability.sequential.world_runs + 3  # + 3 screening runs


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
    assert report.stability is None, "no case-level stability: it pooled runs of different worlds"
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

    def __init__(
        self,
        rng: random.Random,
        base_rate: float,
        world_rate: float,
        base_errors: frozenset[int] = frozenset(),
    ) -> None:
        from tests.data_agents import CsvAgent
        from tests.data_factories import ORDERS

        self.rng = rng
        self.rates = (base_rate, world_rate)
        self.inner = CsvAgent()
        self.orders = ORDERS
        self.calls = 0
        self.base_calls = 0
        self.base_errors = base_errors
        """Numbers (from 1) of the baseline executions that end in an error."""

    def solve(self, question: str, directory: Path) -> Any:
        from isitright.packs.data.adapters import AgentRun

        self.calls += 1
        on_base = (directory / "orders.csv").read_text(encoding="utf-8") == self.orders
        if on_base:
            self.base_calls += 1
            if self.base_calls in self.base_errors:
                return AgentRun(code="", answer=None, error="the agent crashed")
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
    audit: Any, audits: int, base_rate: float, world_rate: float, seed: int, max_trials: int = 20
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
                allow_failing_baseline=True,  # the baseline fails at the simulated rate
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


def _data_case(audit: Any, agent: Any, **config: Any) -> Any:
    from isitright.packs.data.live import LiveConfig, run_live

    settings = {
        "baseline_runs": 3,
        "attempts": 40,
        "max_worlds": 6,
        "verify_minimized_runs": 0,
        "allow_failing_baseline": True,  # these agents fail at a chosen rate, the baseline included
    }
    return run_live(audit, agent, config=LiveConfig(**{**settings, **config}))


def test_data_the_correct_agent_passes_and_the_sentinel_fails_in_every_tested_world(
    data_audit: Any,
) -> None:
    """The null and power runs assume this. They also assume that the agent recognizes the
    baseline by its file: every call it classified as the baseline was a baseline run, so no
    generated world kept the original file and silently took the baseline's failure rate."""
    right = _FlakyDataAgent(random.Random(1), 0.0, 0.0)
    case = _data_case(data_audit, right)
    runs = [w for w in case.worlds if w.run_status != "NOT_RUN" and w.counts and w.counts["n"]]
    assert len(runs) >= 3
    for w in runs:
        assert w.counts["not_met"] == 0 and w.counts["errors"] == 0, w
        assert w.counts["met"] + w.counts["cannot_judge"] == w.counts["n"], w
    wrong = _FlakyDataAgent(random.Random(2), 1.0, 1.0)
    case = _data_case(data_audit, wrong)
    runs = [w for w in case.worlds if w.run_status != "NOT_RUN" and w.counts and w.counts["n"]]
    for w in runs:
        assert (
            w.counts["met"] == 0 and w.counts["not_met"] + w.counts["cannot_judge"] == w.counts["n"]
        )
    made = case.inputs["baseline_runs"]["n"] + case.inputs["paired_baseline_runs"]["n"]
    assert wrong.base_calls == made, "every call on the original file was a baseline run"


def test_data_a_finding_counts_the_baseline_runs_made_for_its_own_world(data_audit: Any) -> None:
    agent = _FlakyDataAgent(random.Random(3), 0.0, 1.0, base_errors=frozenset({5, 8}))
    case = _data_case(data_audit, agent, max_worlds=4)
    sequential = [
        f for f in case.findings if f.stability is not None and f.stability.sequential is not None
    ]
    assert sequential
    injected = 0
    for f in sequential:
        stability = f.stability
        record = stability.sequential
        assert stability.baseline.n == record.baseline_runs
        assert stability.baseline.n != case.inputs["baseline_runs"]["n"] or record.pairs == 0
        assert stability.world.n == record.world_runs + 3  # + the 3 screening runs
        assert record.pairs <= min(record.world_runs, record.baseline_runs)
        assert stability.baseline.errors == record.excluded_errored - stability.world.errors
        injected += stability.baseline.errors
    assert 1 <= injected <= 2, "the two unusable baseline runs are in the worlds they were made for"
    assert case.inputs["baseline_runs"]["n"] == 3, "the preliminary baseline is reported apart"


def test_data_never_reuses_a_baseline_outcome_across_pairs(data_audit: Any) -> None:
    from isitright.packs.data.live import LiveConfig, run_live

    agent = _FlakyDataAgent(random.Random(6), 0.5, 0.5)
    case = run_live(
        data_audit,
        agent,
        config=LiveConfig(
            baseline_runs=3,
            attempts=40,
            max_worlds=4,
            verify_minimized_runs=0,
            allow_failing_baseline=True,
        ),
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
    base_errors: frozenset[int] = frozenset(),
) -> None:
    """Replace the agent command by a copy of a recorded run. ``base_errors`` numbers (from 1) the
    baseline executions that end in a subject error."""
    from isitright.packs.mcp import audit as mcp_audit

    baseline_calls = [0]

    def fake_run_agent(
        argv: list[str],
        run_dir: Path,
        mcp_config: Path,
        task_file: Path,
        world_id: str,
        timeout: float,
    ) -> tuple[str, int]:
        calls.append(world_id)
        if world_id == "baseline":
            baseline_calls[0] += 1
            if baseline_calls[0] in base_errors:
                return "SUBJECT_ERROR", 1
        rate = base_rate if world_id == "baseline" else world_rate
        kind = "bad" if rng.random() < rate else "good"
        source = artifacts["runs"][kind][world_id]
        required = ["state_before.json", "state_after.json"]
        if kind == "good":
            required.append(
                "trace.jsonl"
            )  # the reference procedure calls tools; a refusal does not
        for name in required:
            assert (source / name).is_file(), f"the recorded {kind} run of {world_id} lacks {name}"
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
        only=[artifacts["world"]],
        attempts=2000,
        trust_code=True,
        minimize=False,
        **{"k": 4, **extra},
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


def test_agents_the_recorded_runs_give_the_outcome_matrix_the_tests_rely_on(
    shop_artifacts: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """good (reference procedure): MET on the baseline and on the control world; bad (refusal):
    NOT_MET on both. The fake copies real shop runs; it does not make up verdicts."""
    for n, (rate, expected) in enumerate([(0.0, "MET"), (1.0, "NOT_MET")]):
        _fake_agent(monkeypatch, shop_artifacts, random.Random(n), rate, rate, [])
        report = _agents_audit(tmp_path, shop_artifacts, n, sequential=False, k=2)
        runs = report.cases[0].extensions["mcp"]["runs"]
        assert {r["world_id"] for r in runs} == {"baseline", shop_artifacts["world"]}
        assert all(r["outcome"] == expected for r in runs), [
            (r["world_id"], r["outcome"]) for r in runs
        ]


def test_agents_the_fake_refuses_a_recorded_run_that_lacks_a_file(
    shop_artifacts: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(shop_artifacts["runs"]["good"]["baseline"], broken)
    (broken / "trace.jsonl").unlink()
    artifacts = {
        **shop_artifacts,
        "runs": {
            **shop_artifacts["runs"],
            "good": {**shop_artifacts["runs"]["good"], "baseline": broken},
        },
    }
    _fake_agent(monkeypatch, artifacts, random.Random(1), 0.0, 0.0, [])
    with pytest.raises(AssertionError, match=r"lacks trace\.jsonl"):
        _agents_audit(tmp_path, artifacts, 0, sequential=False, k=1)


def test_agents_a_finding_counts_the_baseline_runs_made_for_its_own_world(
    shop_artifacts: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_agent(
        monkeypatch, shop_artifacts, random.Random(4), 0.0, 1.0, [], base_errors=frozenset({6, 9})
    )
    report = _agents_audit(tmp_path, shop_artifacts, 0)
    (finding,) = [f for f in report.cases[0].findings if f.stability]
    stability = finding.stability
    record = stability.sequential
    assert stability.baseline.n == record.baseline_runs != 4, "not the 4 preliminary runs"
    assert stability.baseline.errors == record.excluded_errored == 2
    assert stability.world.n == record.world_runs + 4  # + the 4 screening runs
    assert record.pairs == record.baseline_runs - 2
    baseline_world = next(w for w in report.cases[0].worlds if w.id == "baseline")
    assert baseline_world.counts["n"] == 4, "the preliminary baseline is reported apart"


def test_agents_runs_carry_distinct_seeds(
    shop_artifacts: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_agent(monkeypatch, shop_artifacts, random.Random(1), 0.4, 0.6, [])
    report = _agents_audit(tmp_path, shop_artifacts, 0)
    seeds = [r["seed"] for r in report.cases[0].extensions["mcp"]["runs"]]
    assert len(seeds) > 8 and len(set(seeds)) == len(seeds)
