"""Live mode with scripted agents: ranking by frozen screening, budgets, not-run worlds, scope."""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")

from isitright.core.evidence import AuditReport, DivergenceStatus
from isitright.core.stochastic import Budget
from isitright.packs.data.audit import AuditConfig, DataAudit
from isitright.packs.data.live import LiveConfig, run_live
from isitright.packs.data.task import load_task
from tests.data_agents import BrokenAgent, FixedProgramAgent
from tests.data_factories import CORRECT, DROPNA_FORGOTTEN, make_task, program


@pytest.fixture(scope="module")
def audit(tmp_path_factory: pytest.TempPathFactory):
    task = load_task(make_task(tmp_path_factory.mktemp("live")))
    with DataAudit(
        task, AuditConfig(attempts=60, trust_code=True, reuse=30, timeout_seconds=20.0)
    ) as value:
        yield value


CONFIG = LiveConfig(
    baseline_runs=2, max_trials=3, attempts=40, max_worlds=6, verify_minimized_runs=2
)


def test_the_live_agent_is_run_on_screened_worlds_and_its_own_runs_are_the_evidence(
    audit: DataAudit,
) -> None:
    recorded = program(DROPNA_FORGOTTEN, "baseline")
    frozen = audit.check_frozen(recorded)
    agent = FixedProgramAgent(audit.host, DROPNA_FORGOTTEN)
    case = run_live(
        audit,
        agent,
        program=recorded,
        config=CONFIG,
        frozen_finding=frozen.findings[0],
        frozen_world=_world(audit, frozen),
    )
    AuditReport.model_validate_json(
        AuditReport(
            pack="data", kind="case", cases=[case], totals=_totals(case), elapsed_seconds=1.0
        ).model_dump_json()
    )
    assert case.subject_kind == "AGENT"
    assert case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    live = [f for f in case.findings if f.world_id != "minimized"]
    assert live and all(f.mode == "live_agent" and f.live is not None for f in live)
    assert all(f.live.agent_runs_only and f.live.not_met > 0 for f in live)
    assert any(f.live.found_by_frozen_replay for f in live)
    assert all(f.fidelity.found_on == "NATIVE_ISOLATED" for f in case.findings)
    assert all(f.fidelity.verified_on == "LIVE_AGENT" for f in case.findings)
    minimized = next(f for f in case.findings if f.world_id == "minimized")
    assert minimized.minimization["rows_after"] <= 3
    assert case.inputs["baseline_runs"]["met"] == 2  # right on the original data


def test_screening_orders_wrong_if_unchanged_first_and_unrun_worlds_are_reported(
    audit: DataAudit,
) -> None:
    recorded = program(DROPNA_FORGOTTEN, "baseline")
    agent = FixedProgramAgent(audit.host, DROPNA_FORGOTTEN)
    case = run_live(audit, agent, program=recorded, config=CONFIG)
    ran = [w for w in case.worlds if w.run_status == "RUN" and w.id != "minimized"]
    not_run = [w for w in case.worlds if w.run_status == "NOT_RUN"]
    assert len(ran) <= CONFIG.max_worlds and not_run
    assert all(w.not_run_reason for w in not_run)
    first = min(ran, key=lambda w: w.screening.rank or 10**9)
    assert first.screening.screening_class == "WRONG_IF_UNCHANGED"
    assert case.search.screening.counts["WRONG_IF_UNCHANGED"] > 0
    assert "never as passing" in " ".join(case.assumptions)


def test_a_run_budget_stops_the_live_runs_and_says_so(audit: DataAudit) -> None:
    recorded = program(CORRECT, "baseline")
    agent = FixedProgramAgent(audit.host, CORRECT)
    case = run_live(audit, agent, program=recorded, config=CONFIG, budget=Budget(runs=4))
    assert agent.calls == 4
    assert any("runs budget exhausted" in (w.not_run_reason or "") for w in case.worlds)
    assert case.divergence_status in {
        DivergenceStatus.NOT_FOUND_WITHIN_BUDGET,
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
    }
    assert "not run" in case.headline


def test_a_correct_agent_has_no_finding_and_that_is_not_called_correctness(
    audit: DataAudit,
) -> None:
    agent = FixedProgramAgent(audit.host, CORRECT)
    case = run_live(audit, agent, program=program(CORRECT, "b"), config=CONFIG)
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert not case.findings and "no disagreement" in case.headline
    assert "correct" not in case.headline.lower()


def test_an_agent_that_returns_no_code_is_counted_as_an_error_run(audit: DataAudit) -> None:
    case = run_live(
        audit,
        BrokenAgent(),
        config=LiveConfig(baseline_runs=1, max_trials=1, attempts=15, max_worlds=2),
    )
    assert case.inputs["baseline_runs"]["errors"] == 1
    assert not case.findings
    assert case.search.screening.counts["UNSCREENABLE"] > 0  # no recorded program to screen with


def test_named_worlds_are_run_even_when_ranked_low(audit: DataAudit) -> None:
    agent = FixedProgramAgent(audit.host, CORRECT)
    case = run_live(
        audit,
        agent,
        config=LiveConfig(baseline_runs=1, max_trials=1, attempts=25),
        only=["missing"],
    )
    assert {w.id for w in case.worlds if w.run_status == "RUN"} <= {"missing", "baseline"} or all(
        w.id.startswith("missing") for w in case.worlds if w.run_status == "RUN"
    )


def _world(audit: DataAudit, frozen):
    from isitright.core.mutations import World

    return World.from_json(audit.artifacts[frozen.findings[0].finding_id].world)


def _totals(case):
    from isitright.core.evidence import totals_of

    return totals_of([case])
