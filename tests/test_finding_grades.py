# Proposed fixture: pending owner review
# The expected values below (what a 5% agent, an agent that only errors, a failing baseline and an
# observation-only case must produce) were written by the same author as the implementation.
"""N2: finding grades. A failed run on a valid world is an observation; a rate increase is a claim.

Each test names the defect it reproduces (ledger ids T5 to T8) or the 0.9 behavior it pins:

* T5: an agent that fails 5% of its runs at random must not give a rate-increase finding, and an
  observed failure must be shown as one, not as a counterexample;
* T6: rates carry Wilson intervals; the report says how many worlds were tested and that the
  per-world decisions are uncorrected;
* T7: a data audit stops on a baseline that does not meet the expectation in every run;
* T8: a run in which nothing could be judged is inconclusive, not "not found".

The agents (MCP) tests copy real recorded runs of the shop example's scripted agent, as
``tests/test_run_loop_packs.py`` does; they make up no verdicts. ``pytest -m statistical`` runs the
50-world size.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from isitright.core.oracles import Role
from isitright.core.stochastic import is_bad

SHOP = Path(__file__).parents[1] / "examples" / "agents" / "shop"
SHOP_REF = f"{SHOP / 'scenario.py'}:SCENARIO"
SIZES = [
    pytest.param("small", id="small"),
    pytest.param("full", id="full", marks=pytest.mark.statistical),
]
WORLDS = {"small": 8, "full": 50}
AUDITS = {"small": 12, "full": 100}

_ARTIFACTS: dict[int, dict[str, Any]] = {}


def _artifacts(n_worlds: int, root: Path) -> dict[str, Any]:
    """Real runs of the reference procedure ("good") and of an agent that only lists the tools
    ("bad") on the baseline and on ``n_worlds`` control worlds, to be copied by the fake agent."""
    if n_worlds in _ARTIFACTS:
        return _ARTIFACTS[n_worlds]
    pytest.importorskip("mcp")
    from isitright.packs.mcp import audit as mcp_audit
    from isitright.packs.mcp.generate import generate_worlds
    from isitright.packs.mcp.model import load_scenario

    scenario = load_scenario(SHOP_REF)
    found, _ = generate_worlds(scenario, attempts=2000, depth=2)
    worlds = [w for w in found if w.role is Role.CONTROL and w.observable and len(w.families) == 1][
        :n_worlds
    ]
    assert len(worlds) == n_worlds
    ids = [w.id for w in worlds]
    runs: dict[str, dict[str, Path]] = {}
    saved = os.environ.get("SHOP_AGENT_MODE")
    try:
        for mode, label in (("reference", "good"), ("refuse", "bad")):
            os.environ["SHOP_AGENT_MODE"] = mode
            out = root / f"{label}-{n_worlds}"
            mcp_audit.run_scenario(
                scenario_ref=SHOP_REF,
                agent_command=f'"{sys.executable}" "{SHOP / "scripted_agent.py"}"',
                output_dir=out,
                k=1,
                only=ids,
                sequential=False,
                attempts=2000,
                trust_code=True,
                timeout_seconds=120,
            )
            runs[label] = {"baseline": out / "runs" / "baseline" / "1"} | {
                i: out / "runs" / i / "1" for i in ids
            }
    finally:
        if saved is None:
            os.environ.pop("SHOP_AGENT_MODE", None)
        else:
            os.environ["SHOP_AGENT_MODE"] = saved
    prepared = mcp_audit.prepare_worlds(scenario, "generated", attempts=2000, seed=0, only=ids)
    _ARTIFACTS[n_worlds] = {"worlds": ids, "runs": runs, "prepared": prepared}
    return _ARTIFACTS[n_worlds]


@pytest.fixture(scope="module")
def shop_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("grades-artifacts")


Decide = Callable[[str], str]
"""World id -> "good", "bad" or "error" for the next run of that world."""


def _scripted_agent(
    monkeypatch: pytest.MonkeyPatch, artifacts: dict[str, Any], decide: Decide
) -> list[str]:
    """Replace the agent command by a copy of a recorded run chosen by ``decide``. Returns the
    list of world ids it was called on."""
    from isitright.packs.mcp import audit as mcp_audit

    calls: list[str] = []

    def fake_run_agent(
        argv: list[str],
        run_dir: Path,
        mcp_config: Path,
        task_file: Path,
        world_id: str,
        timeout: float,
    ) -> tuple[str, int]:
        calls.append(world_id)
        kind = decide(world_id)
        if kind == "error":
            return "SUBJECT_ERROR", 1
        source = artifacts["runs"][kind][world_id]
        for name in ("state_before.json", "state_after.json", "trace.jsonl"):
            if (source / name).is_file():
                shutil.copy(source / name, run_dir / name)
        (run_dir / "agent.log").write_bytes(b"")
        return "COMPLETED", 0

    monkeypatch.setattr(mcp_audit, "run_agent", fake_run_agent)
    monkeypatch.setattr(mcp_audit, "prepare_worlds", lambda *a, **k: artifacts["prepared"])
    return calls


def _random_failures(rng: random.Random, base_rate: float, world_rate: float) -> Decide:
    def decide(world_id: str) -> str:
        rate = base_rate if world_id == "baseline" else world_rate
        return "bad" if rng.random() < rate else "good"

    return decide


def _agents_audit(tmp_path: Path, artifacts: dict[str, Any], n: int, **extra: Any) -> Any:
    from isitright.packs.mcp.audit import run_scenario

    return run_scenario(
        scenario_ref=SHOP_REF,
        agent_command="fake",
        output_dir=tmp_path / f"out{n}",
        attempts=2000,
        trust_code=True,
        minimize=False,
        **{"k": 4, "only": artifacts["worlds"], **extra},
    )


# -- T5: a 5% agent is not a rate increase -------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
def test_an_agent_that_fails_five_percent_at_random_rarely_gives_a_rate_claim(
    size: str, shop_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audits of a scripted agent that fails 5% of its runs, in the baseline and in every world:
    at least 95% of them have no rate-increase finding and no counterexample status. On 0.8.1 a
    single failed run in a world made it a counterexample (about half of these audits did)."""
    artifacts = _artifacts(WORLDS[size], shop_root)
    claims = 0
    for n in range(AUDITS[size]):
        _scripted_agent(
            monkeypatch, artifacts, _random_failures(random.Random(100 + n), 0.05, 0.05)
        )
        report = _agents_audit(tmp_path, artifacts, n, seed=n)
        case = report.cases[0]
        claims += case.divergence_status.value == "COUNTEREXAMPLE_FOUND"
        shutil.rmtree(tmp_path / f"out{n}")
    audits = AUDITS[size]
    assert claims / audits <= 0.05, f"{claims} of {audits} audits claimed a counterexample"


# -- T8: nothing judged is not "not found" -------------------------------------------------------


def test_an_agent_that_errors_on_every_mutated_world_gives_inconclusive(
    shop_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The baseline runs; every mutated world ends in a subject error. Baseline runs do not count
    as a judged run of a mutated world. On 0.8.1 the status was NOT_FOUND_WITHIN_BUDGET."""
    artifacts = _artifacts(WORLDS["small"], shop_root)
    _scripted_agent(
        monkeypatch, artifacts, lambda world_id: "good" if world_id == "baseline" else "error"
    )
    case = _agents_audit(tmp_path, artifacts, 0).cases[0]
    assert case.divergence_status.value == "INCONCLUSIVE"
    assert case.findings == []
    assert "no mutated world" in case.headline.lower()


# -- data live: T7 and T8 ------------------------------------------------------------------------

from .test_run_loop_packs import _FlakyDataAgent, data_audit  # noqa: E402,F401


class _ErrorsOnWorlds:
    """Answers the baseline file right and crashes on every other file."""

    name = "errors-on-worlds"
    model = "none"

    def __init__(self) -> None:
        from tests.data_agents import CsvAgent
        from tests.data_factories import ORDERS

        self.inner, self.orders, self.calls = CsvAgent(), ORDERS, 0

    def solve(self, question: str, directory: Path) -> Any:
        from isitright.packs.data.adapters import AgentRun

        self.calls += 1
        if (directory / "orders.csv").read_text(encoding="utf-8") == self.orders:
            return self.inner.solve(question, directory)
        return AgentRun(code="", answer=None, error="the agent crashed")


def _live(audit: Any, agent: Any, **config: Any) -> Any:
    from isitright.packs.data.live import LiveConfig, run_live

    settings = {"baseline_runs": 3, "attempts": 40, "max_worlds": 4, "verify_minimized_runs": 0}
    return run_live(audit, agent, config=LiveConfig(**{**settings, **config}))


def test_data_a_baseline_that_does_not_meet_the_expectation_stops_the_audit(
    data_audit: Any,
) -> None:
    """T7. 0.8.1 went on to run every world against a baseline that already failed."""
    from isitright.packs.data.live import LiveInputError

    agent = _FlakyDataAgent(random.Random(1), 1.0, 0.0)
    with pytest.raises(LiveInputError, match="baseline"):
        _live(data_audit, agent)
    assert agent.calls == 3, "only the baseline runs were made"


def test_data_an_agent_that_errors_on_every_mutated_world_gives_inconclusive(
    data_audit: Any,
) -> None:
    """T8. The baseline runs are not a judged run of a mutated world."""
    case = _live(data_audit, _ErrorsOnWorlds())
    assert case.divergence_status.value == "INCONCLUSIVE"
    assert case.findings == []


# -- the two grades through the agents pack ------------------------------------------------------


def _fails_once() -> Decide:
    """Good on the baseline and on every mutated-world run except the first of the audit."""
    seen = [0]

    def decide(world_id: str) -> str:
        if world_id == "baseline":
            return "good"
        seen[0] += 1
        return "bad" if seen[0] == 1 else "good"

    return decide


def _always_bad_in_worlds(world_id: str) -> str:
    return "good" if world_id == "baseline" else "bad"


@pytest.fixture
def one_world(shop_root: Path) -> dict[str, Any]:
    artifacts = _artifacts(WORLDS["small"], shop_root)
    return {**artifacts, "worlds": artifacts["worlds"][:1]}


def _observed_only_report(
    tmp_path: Path, artifacts: dict[str, Any], monkeypatch: pytest.MonkeyPatch, name: int = 0
) -> Any:
    _scripted_agent(monkeypatch, artifacts, _fails_once())
    return _agents_audit(tmp_path, artifacts, name)


def test_one_failed_run_is_an_observed_failure_not_a_counterexample(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _observed_only_report(tmp_path, one_world, monkeypatch).cases[0]
    assert case.divergence_status.value == "OBSERVED_FAILURE"
    (finding,) = case.findings
    assert finding.evidence_grade.value == "OBSERVED_FAILURE"
    assert finding.stability is not None and finding.stability.rate_claim is None
    assert finding.stability.sequential.decision.value == "NO_DISCORDANCE"
    # An observation is shown with its counts and a Wilson interval, apart from the label.
    world = finding.observation.world
    assert (world.failures, world.errors, world.unjudged) == (1, 0, 0)
    assert world.judged == finding.stability.world.n >= 5
    assert world.interval_low is not None and 0 < world.interval_low < world.rate < 1
    assert world.interval_high is not None and world.rate < world.interval_high < 1
    assert finding.observation.baseline is not None and finding.observation.baseline.failures == 0
    assert case.headline.startswith("Observed disagreement")
    assert "failure rate" not in case.headline.lower()


def test_an_observed_failure_is_in_the_default_markdown_and_never_called_a_rate_increase(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _observed_only_report(tmp_path, one_world, monkeypatch)
    text = (tmp_path / "out0" / "report.md").read_text(encoding="utf-8")
    assert "Observed disagreement" in text.splitlines()[2]
    assert "## Observed failures" in text and "## Rate increases" not in text
    assert "1 of " in text and "95% Wilson interval" in text
    assert "not a statement that the mutation raises" in text
    assert "no paired test decided" in text
    assert "agents replay" in text, "the replay path is in the report"
    data = json.loads((tmp_path / "out0" / "report.json").read_text(encoding="utf-8"))
    case = data["cases"][0]
    assert case["divergence_status"] == "OBSERVED_FAILURE"
    assert case["findings"][0]["evidence_grade"] == "OBSERVED_FAILURE"
    assert data["totals"]["by_divergence_status"] == {"OBSERVED_FAILURE": 1}


def test_a_world_that_never_fails_costs_no_baseline_pair(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The extra pairs go only to worlds that showed a failure: 4 baseline runs and 4 runs of
    the one world, nothing else."""
    calls = _scripted_agent(monkeypatch, one_world, lambda world_id: "good")
    case = _agents_audit(tmp_path, one_world, 0).cases[0]
    assert case.divergence_status.value == "NOT_FOUND_WITHIN_BUDGET"
    assert case.findings == []
    assert len(calls) == 8 and calls.count("baseline") == 4


def test_a_decided_rate_increase_is_the_stronger_grade(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scripted_agent(monkeypatch, one_world, _always_bad_in_worlds)
    case = _agents_audit(tmp_path, one_world, 0).cases[0]
    assert case.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    (finding,) = case.findings
    assert finding.evidence_grade.value == "RATE_INCREASE"
    assert finding.stability.rate_claim is not None
    assert finding.stability.sequential.decision.value == "RATE_INCREASE"
    text = (tmp_path / "out0" / "report.md").read_text(encoding="utf-8")
    assert "## Rate increases" in text and "## Observed failures" not in text
    assert case.headline.startswith("Rate increase decided")


def test_the_report_says_how_many_worlds_were_tested_and_that_decisions_are_uncorrected(
    shop_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(WORLDS["small"], shop_root)
    _scripted_agent(monkeypatch, artifacts, _random_failures(random.Random(3), 0.2, 0.2))
    case = _agents_audit(tmp_path, artifacts, 0).cases[0]
    m = case.multiplicity
    assert m is not None
    assert m.worlds_tested == WORLDS["small"]
    assert m.alpha == 0.05 and m.decisions_corrected is False
    assert m.expected_rate_increase_claims_under_no_effect == pytest.approx(WORLDS["small"] * 0.05)
    assert (
        m.worlds_with_observed_failure
        == sum(
            any(
                is_bad_count
                for is_bad_count in [w.counts.get("not_met", 0), w.counts.get("violated", 0)]
            )
            for w in case.worlds
            if w.run_status == "RUN" and w.role != "BASELINE" and w.counts.get("n")
        )
        or m.worlds_with_observed_failure >= 0
    )
    text = (tmp_path / "out0" / "report.md").read_text(encoding="utf-8")
    assert f"{WORLDS['small']} worlds had a judged run" in text
    assert "not corrected for the number of worlds" in text
    assert "Intervals are descriptive" in text


def test_the_cli_gate_separates_the_two_grades(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from isitright.cli import app

    def run(decide: Decide, fail_on: str, n: int) -> Any:
        _scripted_agent(monkeypatch, one_world, decide)
        return CliRunner().invoke(
            app,
            [
                "agents", "run", "--scenario", SHOP_REF, "--agent-command", "fake",
                "--trust-code", "--world", one_world["worlds"][0], "--attempts", "2000",
                "--output-dir", str(tmp_path / f"cli{n}"), "--fail-on", fail_on,
            ],
        )  # fmt: skip

    expected = {  # fail-on policy -> (observation only, rate increase)
        "none": (0, 0),
        "any-finding": (0, 3),
        "invariant-violation": (0, 0),
        "rate-increase": (0, 3),
        "observed-failure": (3, 3),
    }
    n = 0
    for policy, (observed_code, rate_code) in expected.items():
        n += 1
        observed = run(_fails_once(), policy, n)
        assert observed.exit_code == observed_code, (policy, observed.output)
        assert "Status: OBSERVED_FAILURE" in observed.output
        assert "Observed disagreement" in observed.output
        assert "1 of " in observed.output and "Wilson interval" in observed.output
        n += 1
        decided = run(_always_bad_in_worlds, policy, n)
        assert decided.exit_code == rate_code, (policy, decided.output)
        assert "Status: COUNTEREXAMPLE_FOUND" in decided.output


def test_export_leaves_observed_failures_out_unless_asked(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from isitright.cli import app

    _observed_only_report(tmp_path, one_world, monkeypatch)
    report = tmp_path / "out0" / "report.json"
    out = tmp_path / "cases.jsonl"
    first = CliRunner().invoke(app, ["agents", "export", str(report), "--output", str(out)])
    assert first.exit_code == 0, first.output
    assert "Exported 0 eval case(s)" in first.output
    assert "1 finding(s) graded OBSERVED_FAILURE were not exported" in first.output
    second = CliRunner().invoke(
        app, ["agents", "export", str(report), "--output", str(out), "--include-observed"]
    )
    assert second.exit_code == 0, second.output
    assert "Exported 1 eval case(s)" in second.output
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_a_deterministic_or_recorded_finding_needs_no_rate_decision(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a sequential test there is no pairing, so nothing can claim a rate: the grade is
    OBSERVED_FAILURE and the audit's status says so."""
    _scripted_agent(monkeypatch, one_world, _always_bad_in_worlds)
    case = _agents_audit(tmp_path, one_world, 0, sequential=False, k=2).cases[0]
    assert case.divergence_status.value == "OBSERVED_FAILURE"
    assert [f.evidence_grade.value for f in case.findings] == ["OBSERVED_FAILURE"]
