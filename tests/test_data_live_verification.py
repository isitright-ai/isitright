# Proposed fixture: pending owner review
# Expected values written by the author of the implementation.
"""N2 follow-up: the minimized-world verification is reported apart from the generated worlds.

The live search runs the agent on generated worlds. A frozen finding's minimized world is run
separately. Its outcome is visible, may decide the case status, and is never counted among the
generated worlds or in the multiplicity of the search.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")

from isitright.core.evidence import AuditReport, DivergenceStatus, totals_of
from isitright.core.mutations import World
from isitright.core.stochastic import Budget
from isitright.packs.data.adapters import AgentRun
from isitright.packs.data.audit import AuditConfig, DataAudit
from isitright.packs.data.live import LiveConfig, run_live
from isitright.packs.data.reports import markdown
from isitright.packs.data.task import load_task
from tests.data_agents import FixedProgramAgent
from tests.data_factories import CORRECT, DROPNA_FORGOTTEN, make_task, program

CONFIG = LiveConfig(
    baseline_runs=2, max_trials=3, attempts=40, max_worlds=4, verify_minimized_runs=3
)


@pytest.fixture(scope="module")
def audit(tmp_path_factory: pytest.TempPathFactory) -> Any:
    task = load_task(make_task(tmp_path_factory.mktemp("verification")))
    with DataAudit(
        task, AuditConfig(attempts=60, trust_code=True, reuse=30, timeout_seconds=20.0)
    ) as value:
        yield value


class _WrongOnlyOnTheMinimizedWorld:
    """Right everywhere, except on the one dataset that is the minimized counterexample."""

    name = "wrong-only-on-the-minimized-world"
    model = "none"

    def __init__(self, audit: DataAudit, minimized_csv: str) -> None:
        self.inner = FixedProgramAgent(audit.host, CORRECT)
        self.minimized_csv = minimized_csv
        self.on_minimized = 0

    def solve(self, question: str, directory: Path) -> AgentRun:
        if (directory / "orders.csv").read_text(encoding="utf-8") == self.minimized_csv:
            self.on_minimized += 1
            return AgentRun(code="", answer="@north_mean[-1.00]", input_tokens=1, output_tokens=1)
        return self.inner.solve(question, directory)


def _frozen(audit: DataAudit) -> tuple[Any, World]:
    frozen = audit.check_frozen(program(DROPNA_FORGOTTEN, "baseline"))
    finding = frozen.findings[0]
    return finding, World.from_json(audit.artifacts[finding.finding_id].world)


def _generated(case: Any) -> list[Any]:
    return [
        w
        for w in case.worlds
        if w.run_status == "RUN" and w.id not in ("baseline", "minimized") and w.counts.get("n")
    ]


def test_a_failure_found_only_on_the_minimized_world_is_not_a_generated_world_finding(
    audit: DataAudit,
) -> None:
    finding, world = _frozen(audit)
    agent = _WrongOnlyOnTheMinimizedWorld(audit, audit.data_files(world.state)["orders.csv"])
    case = run_live(
        audit, agent, program=program(DROPNA_FORGOTTEN, "baseline"), config=CONFIG,
        frozen_finding=finding, frozen_world=world,
    )  # fmt: skip
    # visible, and it decides the status
    assert case.divergence_status is DivergenceStatus.OBSERVED_FAILURE
    (verified,) = case.findings
    assert verified.world_id == "minimized" and verified.finding_id.endswith(":live:minimized")
    assert verified.evidence_grade.value == "OBSERVED_FAILURE"
    assert verified.divergence["search_scope"] == "minimized_verification"
    assert "not one of the generated worlds" in verified.divergence["scope"]
    assert agent.on_minimized == CONFIG.verify_minimized_runs
    # recorded apart, with its own counts
    record = case.extensions["data"]["verification"]
    assert (record["runs"], record["failures"], record["judged"], record["errors"]) == (3, 3, 3, 0)
    assert record["status"] == "OBSERVED_FAILURE" and record["frozen_finding"] == finding.finding_id
    assert record["finding"] == verified.finding_id
    # the generated worlds: no failure, and the multiplicity counts only them
    generated = _generated(case)
    assert generated and all(w.counts["not_met"] == 0 for w in generated)
    m = case.multiplicity
    assert m is not None
    assert m.worlds_tested == len(generated)
    assert (m.worlds_with_observed_failure, m.worlds_with_rate_increase) == (0, 0)
    # the wording does not say the search found it
    assert f"no disagreement in the {len(generated)} generated worlds" in case.headline
    assert "separately, on the minimized frozen counterexample" in case.headline
    assert "differed in 3 of 3 judged runs" in case.headline
    report = AuditReport(
        pack="data", kind="case", cases=[case], totals=totals_of([case]), elapsed_seconds=0
    )
    text = markdown(report)
    assert "separate verification, not a generated world" in text


def test_findings_in_both_activities_are_counted_once_each(audit: DataAudit) -> None:
    finding, world = _frozen(audit)
    agent = FixedProgramAgent(audit.host, DROPNA_FORGOTTEN)  # wrong wherever an amount is blank
    case = run_live(
        audit, agent, program=program(DROPNA_FORGOTTEN, "baseline"), config=CONFIG,
        frozen_finding=finding, frozen_world=world,
    )  # fmt: skip
    ids = [f.finding_id for f in case.findings]
    assert len(ids) == len(set(ids))
    verified = [f for f in case.findings if f.world_id == "minimized"]
    searched = [f for f in case.findings if f.world_id != "minimized"]
    assert len(verified) == 1 and searched
    generated = _generated(case)
    m = case.multiplicity
    assert m is not None
    assert m.worlds_tested == len(generated)
    assert m.worlds_with_observed_failure == len(searched), "the verification is not among them"
    assert m.worlds_with_observed_failure <= m.worlds_tested
    record = case.extensions["data"]["verification"]
    assert record["failures"] == 3 and record["finding"] == verified[0].finding_id
    assert (
        f"differed from the reference in {len(searched)} of {len(generated)} generated worlds"
        in case.headline
    )
    assert "separately, on the minimized frozen counterexample" in case.headline
    # the world records keep the minimized world listed apart from the generated ones
    assert sum(w.id == "minimized" for w in case.worlds) == 1


def test_no_verification_means_no_verification_record(audit: DataAudit) -> None:
    agent = FixedProgramAgent(audit.host, CORRECT)
    case = run_live(
        audit,
        agent,
        config=LiveConfig(
            baseline_runs=2, max_trials=3, attempts=40, max_worlds=2, verify_minimized_runs=0
        ),
    )
    assert case.extensions["data"]["verification"] is None
    assert "separately" not in case.headline


def test_a_report_names_a_replay_artifact_only_for_a_finding_that_has_one(
    audit: DataAudit, tmp_path: Path
) -> None:
    from isitright.packs.data.reports import build_report, write_report

    finding, world = _frozen(audit)
    agent = FixedProgramAgent(audit.host, DROPNA_FORGOTTEN)
    case = run_live(
        audit, agent, program=program(DROPNA_FORGOTTEN, "baseline"), config=CONFIG,
        frozen_finding=finding, frozen_world=world,
    )  # fmt: skip
    assert case.findings
    write_report(build_report([case], 0.1, kind="case"), tmp_path / "none", {})
    bare = json.loads((tmp_path / "none" / "report.json").read_text(encoding="utf-8"))
    for f in bare["cases"][0]["findings"]:
        assert f["replay"]["artifact"] is None and f["replay"]["command"] is None
    write_report(build_report([case], 0.1, kind="case"), tmp_path / "all", audit.artifacts)
    full = json.loads((tmp_path / "all" / "report.json").read_text(encoding="utf-8"))
    commands = [f["replay"]["command"] for f in full["cases"][0]["findings"]]
    assert all(c and "--finding" in c for c in commands)
    for f in full["cases"][0]["findings"]:
        assert (tmp_path / "all" / f["replay"]["artifact"]).is_file()
    numbers = [int(c.split("--finding ")[1].split()[0]) for c in commands]
    assert numbers == list(range(1, len(commands) + 1))


# -- the three outcomes of the separate verification ---------------------------------------------


class _ErrorsOnTheMinimizedWorld(_WrongOnlyOnTheMinimizedWorld):
    """Right everywhere except that it crashes on the minimized counterexample."""

    name = "errors-on-the-minimized-world"

    def solve(self, question: str, directory: Path) -> AgentRun:
        if (directory / "orders.csv").read_text(encoding="utf-8") == self.minimized_csv:
            self.on_minimized += 1
            return AgentRun(code="", answer=None, error="the agent crashed")
        return self.inner.solve(question, directory)


def _verified(audit: DataAudit, agent: Any, **kwargs: Any) -> Any:
    finding, world = _frozen(audit)
    return run_live(
        audit, agent, program=program(DROPNA_FORGOTTEN, "baseline"), config=CONFIG,
        frozen_finding=finding, frozen_world=world, **kwargs,
    )  # fmt: skip


def test_a_verification_with_judged_runs_and_no_failure_is_not_reproduced(
    audit: DataAudit,
) -> None:
    case = _verified(audit, FixedProgramAgent(audit.host, CORRECT))
    record = case.extensions["data"]["verification"]
    assert record["status"] == "NOT_REPRODUCED"
    assert (record["runs"], record["judged"], record["failures"], record["errors"]) == (3, 3, 0, 0)
    assert (
        case.findings == [] and case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    )
    assert "the answer did not differ in 3 judged runs" in case.headline


def test_a_verification_in_which_every_run_errors_is_inconclusive_not_not_reproduced(
    audit: DataAudit,
) -> None:
    _, world = _frozen(audit)
    agent = _ErrorsOnTheMinimizedWorld(audit, audit.data_files(world.state)["orders.csv"])
    case = _verified(audit, agent)
    assert agent.on_minimized == CONFIG.verify_minimized_runs
    record = case.extensions["data"]["verification"]
    assert record["status"] == "INCONCLUSIVE" and record["grade"] is None
    assert (record["runs"], record["judged"], record["failures"], record["errors"]) == (3, 0, 0, 3)
    assert case.findings == []
    assert "NOT_REPRODUCED" not in json.dumps(case.extensions["data"])
    assert "no run was judged (3 of 3 runs ended in an error)" in case.headline
    assert "did not differ in" not in case.headline
    assert "neither reproduced nor ruled out" in case.headline
    # the generated worlds were clean and judged: that part of the verdict is unchanged
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert case.multiplicity is not None and case.multiplicity.worlds_tested >= 1


def test_a_verification_stopped_by_an_exhausted_budget_is_inconclusive(
    audit: DataAudit,
) -> None:
    """The budget is exactly what baseline and search use: the verification gets no run."""
    _, world = _frozen(audit)
    csv = audit.data_files(world.state)["orders.csv"]
    probe = _WrongOnlyOnTheMinimizedWorld(audit, csv)
    _verified(audit, probe)
    search_runs = probe.inner.calls
    assert search_runs > 0 and probe.on_minimized == CONFIG.verify_minimized_runs
    agent = _WrongOnlyOnTheMinimizedWorld(audit, csv)
    case = _verified(audit, agent, budget=Budget(runs=search_runs))
    assert agent.on_minimized == 0, "the verification made no run"
    record = case.extensions["data"]["verification"]
    assert record["status"] == "INCONCLUSIVE" and record["stopped_by"] == "runs"
    assert (record["runs"], record["judged"], record["failures"]) == (0, 0, 0)
    assert record["requested_runs"] == CONFIG.verify_minimized_runs
    assert case.findings == []
    assert "no run was judged (the runs budget was spent first)" in case.headline
    assert "did not differ" not in case.headline and "NOT_REPRODUCED" not in json.dumps(
        case.extensions["data"]
    )
