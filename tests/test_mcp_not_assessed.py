# Proposed fixture: pending owner review
# Expected values written by the author of the implementation.
"""N2 follow-up: a fixed world with no validator runs and is graded, and is never called valid.

The booking scenario's fixed worlds are copied without their validators. The real demo agent runs
on them through `run_scenario`. An explicitly invalid world is added and must not run.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from isitright.packs.mcp import audit as mcp_audit
from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.model import load_scenario

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"
SCENARIO_REF = f"{EXAMPLES / 'booking_scenario.py'}:SCENARIO"
DEMO = f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"'
TRAP, CONTROL = "booked_24h_01m", "flight_cancelled"


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, world: str, **kwargs: Any
) -> tuple[Any, Path]:
    scenario = load_scenario(SCENARIO_REF)
    unvalidated = [dataclasses.replace(w, validate=None) for w in scenario.fixed_worlds]
    invalid = dataclasses.replace(
        scenario.fixed_worlds[0],
        id="explicitly_invalid",
        validate=lambda state: ["this state cannot exist"],
    )
    modified = dataclasses.replace(scenario, fixed_worlds=[*unvalidated, invalid])
    monkeypatch.setattr(mcp_audit, "load_scenario", lambda reference: modified)
    monkeypatch.setenv("DEMO_AGENT_MODE", mode)
    out = tmp_path / "out"
    report = run_scenario(
        scenario_ref=SCENARIO_REF,
        agent_command=DEMO,
        output_dir=out,
        worlds="fixed",
        k=1,
        only=[world],
        trust_code=True,
        timeout_seconds=120,
        **kwargs,
    )
    return report, out


def _check(report: Any, out: Path, world: str, grade: str) -> None:
    case = report.cases[0]
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    markdown = (out / "report.md").read_text(encoding="utf-8")
    runs = case.extensions["mcp"]["runs"]
    # the run and the finding stay visible
    assert any(r["world_id"] == world for r in runs)
    (finding,) = [f for f in case.findings if f.world_id == world]
    assert finding.evidence_grade.value == grade
    # NOT_ASSESSED is preserved, in the finding, the world list and the case, with no tier made up
    assert finding.validity.status == "NOT_ASSESSED" and finding.validity.tiers == []
    record = next(w for w in case.worlds if w.id == world)
    assert record.validity.status == "NOT_ASSESSED" and record.validity.tiers == []
    assert case.validity.status == "NOT_ASSESSED" and case.validity.tiers == []
    assert "no validity tier is claimed for the case" in " ".join(case.validity.notes)
    assert data["cases"][0]["validity"]["status"] == "NOT_ASSESSED"
    assert data["cases"][0]["findings"][0]["validity"] == {
        "status": "NOT_ASSESSED", "tiers": [], "problems": [], "unobservable": False, "notes": [],
    }  # fmt: skip
    # the Markdown says so, and never says a validation happened
    assert "Validity: NOT_ASSESSED." in markdown
    assert "World validity: NOT_ASSESSED (no validation was run on this world" in markdown
    assert f"| {world} |" in markdown and "NOT_ASSESSED" in markdown.split(f"| {world} |")[1]
    summary, findings_text = markdown.split("| World |")[0], markdown.split("## Findings")[1]
    for text in (case.headline, summary, findings_text):
        assert "DOMAIN_VALIDATED" not in text and "STRUCTURAL" not in text
    for text in (case.headline, markdown):
        assert "validated world" not in text and "valid world" not in text.lower()
    # the explanatory text qualifies what the grade says about the world
    assert ("was not)" if grade == "OBSERVED_FAILURE" else "separate validity") in markdown
    # an explicitly invalid world is not executed
    assert not any(r["world_id"] == "explicitly_invalid" for r in runs)


def test_an_observed_failure_on_an_unvalidated_fixed_world_is_kept_and_not_called_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, out = _run(tmp_path, monkeypatch, "careless", TRAP, sequential=False)
    assert report.cases[0].divergence_status.value == "OBSERVED_FAILURE"
    assert report.cases[0].headline.startswith("Observed disagreement")
    _check(report, out, TRAP, "OBSERVED_FAILURE")


def test_a_rate_increase_on_an_unvalidated_fixed_world_is_conditional_on_that_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, out = _run(tmp_path, monkeypatch, "refuse", CONTROL)
    assert report.cases[0].divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert report.cases[0].headline.startswith("Rate increase decided")
    _check(report, out, CONTROL, "RATE_INCREASE")
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "about the world as run" in text and "separate validity" in text


def test_an_explicitly_invalid_world_is_excluded_even_when_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _ = _run(tmp_path, monkeypatch, "careless", "explicitly_invalid", sequential=False)
    case = report.cases[0]
    assert not any(r["world_id"] == "explicitly_invalid" for r in case.extensions["mcp"]["runs"])
    record = next(w for w in case.worlds if w.id == "explicitly_invalid")
    assert record.validity.status == "INVALID" and "cannot exist" in " ".join(
        record.validity.problems
    )
    assert case.findings == []
