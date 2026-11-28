# ruff: noqa: F811
# Proposed fixture: pending owner review
# The expected values below (what a 5% agent, an agent that only errors, a failing baseline and an
# observation-only case must produce) were written by the same author as the implementation.
"""N2: finding grades. A failed run on a valid world is an observation; a rate increase is a claim.

Each test names the defect it reproduces or the 0.9 behavior it pins:

* an agent that fails 5% of its runs at random must not give a rate-increase finding, and an
  observed failure must be shown as one, not as a counterexample;
* rates carry Wilson intervals; the report says how many worlds were tested and that the
  per-world decisions are uncorrected;
* a data audit stops on a baseline that does not meet the expectation in every run;
* a run in which nothing could be judged is inconclusive, not "not found".

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
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from isitright.core.oracles import Role

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
    # Record a few more worlds than asked for: a recording can fail (a timeout on a busy machine),
    # and a world whose recorded run is missing would silently be judged as a failure.
    spare = max(4, n_worlds // 2)
    candidates = [
        w for w in found if w.role is Role.CONTROL and w.observable and len(w.families) == 1
    ][: n_worlds + spare]
    assert len(candidates) >= n_worlds
    ids = [w.id for w in candidates]
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
                timeout_seconds=300,
            )
            runs[label] = {"baseline": out / "runs" / "baseline" / "1"} | {
                i: out / "runs" / i / "1" for i in ids
            }
    finally:
        if saved is None:
            os.environ.pop("SHOP_AGENT_MODE", None)
        else:
            os.environ["SHOP_AGENT_MODE"] = saved

    def recorded(world_id: str) -> bool:
        files = {"good": ("state_before.json", "state_after.json", "trace.jsonl")}
        files["bad"] = files["good"][:2]  # a refusal makes no tool call: no trace
        return all(
            (runs[label][world_id] / name).is_file()
            for label, names in files.items()
            for name in names
        )

    assert recorded("baseline"), "the baseline was not recorded"
    ids = [i for i in ids if recorded(i)][:n_worlds]
    assert len(ids) == n_worlds, f"only {len(ids)} of {n_worlds} worlds were recorded"
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
        for name in ("state_before.json", "state_after.json"):
            assert (source / name).is_file(), f"the recorded {kind} run of {world_id} lacks {name}"
            shutil.copy(source / name, run_dir / name)
        if (source / "trace.jsonl").is_file():  # a recorded refusal makes no tool call
            shutil.copy(source / "trace.jsonl", run_dir / "trace.jsonl")
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


# -- a 5% agent is not a rate increase -------------------------------------------------------


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


# -- nothing judged is not "not found" -------------------------------------------------------


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


# -- data live ------------------------------------------------------------------------

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
    """0.8.1 went on to run every world against a baseline that already failed."""
    from isitright.packs.data.live import LiveInputError

    agent = _FlakyDataAgent(random.Random(1), 1.0, 0.0)
    with pytest.raises(LiveInputError, match="baseline"):
        _live(data_audit, agent)
    assert agent.calls == 3, "only the baseline runs were made"


def test_data_an_agent_that_errors_on_every_mutated_world_gives_inconclusive(
    data_audit: Any,
) -> None:
    """The baseline runs are not a judged run of a mutated world."""
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
    assert "World change: " in text, "the concrete change to the world is in the report"
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


def test_failure_free_worlds_each_cost_exactly_k_runs_and_no_pair(
    shop_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two worlds that never fail, k = 3: the baseline once with k runs, each world k screening
    runs, no paired baseline run: k + 2k = 9 executions, counted by world."""
    artifacts = _artifacts(WORLDS["small"], shop_root)
    two = {**artifacts, "worlds": artifacts["worlds"][:2]}
    k = 3
    calls = _scripted_agent(monkeypatch, two, lambda world_id: "good")
    case = _agents_audit(tmp_path, two, 0, k=k).cases[0]
    first, second = two["worlds"]
    assert Counter(calls) == {"baseline": k, first: k, second: k}
    assert len(calls) == k + 2 * k
    runs = case.extensions["mcp"]["runs"]
    assert Counter(r["world_id"] for r in runs) == {"baseline": k, first: k, second: k}
    assert case.divergence_status.value == "NOT_FOUND_WITHIN_BUDGET" and case.findings == []
    assert all(w.counts["n"] == k for w in case.worlds if w.run_status == "RUN")
    assert case.multiplicity.worlds_tested == 2


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
    # Counted independently, from the run records: mutated worlds only (no baseline, no world that
    # was not run), a judged failure being a run that missed the expectation or broke an invariant.
    judged: dict[str, int] = {}
    failed: dict[str, int] = {}
    for run in case.extensions["mcp"]["runs"]:
        if run["world_id"] == "baseline" or run["run_status"] != "COMPLETED":
            continue
        if run["outcome"] in ("MET", "NOT_MET") or run["violations"]:
            judged[run["world_id"]] = judged.get(run["world_id"], 0) + 1
            if run["outcome"] == "NOT_MET" or run["violations"]:
                failed[run["world_id"]] = failed.get(run["world_id"], 0) + 1
    assert len(judged) == m.worlds_tested == WORLDS["small"]
    assert len(failed) == m.worlds_with_observed_failure
    assert 0 < m.worlds_with_observed_failure < m.worlds_tested, "the fixture must exercise both"
    rate = {f.world_id for f in case.findings if f.evidence_grade.value == "RATE_INCREASE"}
    assert m.worlds_with_rate_increase == len(rate)
    assert rate <= set(failed), "a rate-increase world also counts as one with an observed failure"
    assert {f.world_id for f in case.findings} == set(failed)
    text = (tmp_path / "out0" / "report.md").read_text(encoding="utf-8")
    assert f"{WORLDS['small']} worlds had a judged run" in text
    assert "not corrected for the number of worlds" in text
    assert "nominal upper bound" in text and "not a measured rate" in text
    assert "no family-wise error guarantee" in text
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
    example = json.loads(report.read_text(encoding="utf-8"))["cases"][0]["findings"][0]
    run_dir = report.parent / example["divergence"]["example_run_dir"]
    # The recorded refusal called no tool, so the run left no trace file: nothing is added here.
    assert not (run_dir / "trace.jsonl").exists()
    first = CliRunner().invoke(app, ["agents", "export", str(report), "--output", str(out)])
    assert first.exit_code == 0, first.output
    assert "Exported 0 eval case(s)" in first.output
    assert "1 finding(s) graded OBSERVED_FAILURE were not exported" in first.output
    second = CliRunner().invoke(
        app, ["agents", "export", str(report), "--output", str(out), "--include-observed"]
    )
    assert second.exit_code == 0, second.output
    assert "Exported 1 eval case(s)" in second.output
    (line,) = out.read_text(encoding="utf-8").splitlines()
    exported = json.loads(line)
    assert exported["payload"]["trace"] == [], "no tool call, so an empty trace"
    assert exported["payload"]["world"] and exported["expectation"]["disagreement"]
    assert not (run_dir / "trace.jsonl").exists(), "export fabricated no trace file"


def test_export_refuses_a_missing_trace_when_tool_calls_were_recorded(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing trace file means "no tool call" only when the run recorded none."""
    from typer.testing import CliRunner

    from isitright.cli import app

    _observed_only_report(tmp_path, one_world, monkeypatch)
    report = tmp_path / "out0" / "report.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    example = data["cases"][0]["findings"][0]["divergence"]["example_run_dir"]
    run = next(r for r in data["cases"][0]["extensions"]["mcp"]["runs"] if r["run_dir"] == example)
    assert run["tool_calls"] == 0 and not (report.parent / example / "trace.jsonl").exists()
    args = ["agents", "export", str(report), "--output", str(tmp_path / "x.jsonl")]
    args.append("--include-observed")
    ok = CliRunner().invoke(app, args)  # no tool call, no file: an empty trace
    assert ok.exit_code == 0, ok.output
    # The same run, now recorded as having called three tools while its trace file is gone.
    run["tool_calls"] = 3
    report.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "x.jsonl").unlink()
    refused = CliRunner().invoke(app, args)
    assert refused.exit_code == 2, refused.output
    assert "missing but the run recorded 3 tool call(s)" in refused.output
    assert not (tmp_path / "x.jsonl").exists() or (tmp_path / "x.jsonl").read_text() == ""


def test_export_still_refuses_a_missing_world_and_a_malformed_trace(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from isitright.cli import app

    _observed_only_report(tmp_path, one_world, monkeypatch)
    report = tmp_path / "out0" / "report.json"
    example = json.loads(report.read_text(encoding="utf-8"))["cases"][0]["findings"][0]
    run_dir = report.parent / example["divergence"]["example_run_dir"]
    args = [
        "agents",
        "export",
        str(report),
        "--output",
        str(tmp_path / "x.jsonl"),
        "--include-observed",
    ]
    (run_dir / "trace.jsonl").write_text("{not json\n", encoding="utf-8")
    assert CliRunner().invoke(app, args).exit_code == 2
    (run_dir / "trace.jsonl").unlink()
    world = run_dir / "world.json"
    saved = world.read_text(encoding="utf-8")
    world.unlink()
    try:
        failed = CliRunner().invoke(app, args)
    finally:
        world.write_text(saved, encoding="utf-8")
    assert failed.exit_code == 2 and "Export error" in failed.output


def test_a_deterministic_or_recorded_finding_needs_no_rate_decision(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a sequential test there is no pairing, so nothing can claim a rate: the grade is
    OBSERVED_FAILURE and the audit's status says so."""
    _scripted_agent(monkeypatch, one_world, _always_bad_in_worlds)
    case = _agents_audit(tmp_path, one_world, 0, sequential=False, k=8).cases[0]
    assert case.divergence_status.value == "OBSERVED_FAILURE"
    assert [f.evidence_grade.value for f in case.findings] == ["OBSERVED_FAILURE"]
    # 8 failing runs against 8 passing baseline runs would give a McNemar claim by run index
    stability = case.findings[0].stability
    assert stability.rate_claim is None and "no rate claim" in stability.note


# -- the data pack ---------------------------------------------------------------------------


class _WrongOnce(_FlakyDataAgent):
    """The _FlakyDataAgent's right answers, with exactly one wrong one: the first run on a file
    that is not the baseline's."""

    def __init__(self) -> None:
        super().__init__(random.Random(0), 0.0, 0.0)
        self.wrong = 0

    def solve(self, question: str, directory: Path) -> Any:
        from isitright.packs.data.adapters import AgentRun

        on_base = (directory / "orders.csv").read_text(encoding="utf-8") == self.orders
        if not on_base and self.wrong == 0:
            self.wrong, self.calls = 1, self.calls + 1
            return AgentRun(code="# wrong", answer=-1.0, input_tokens=5, output_tokens=5)
        return super().solve(question, directory)


def test_data_one_wrong_run_is_an_observed_failure_with_counts(data_audit: Any) -> None:
    case = _live(data_audit, _WrongOnce(), max_worlds=2)
    assert case.divergence_status.value == "OBSERVED_FAILURE"
    (finding,) = case.findings
    assert finding.evidence_grade.value == "OBSERVED_FAILURE"
    assert finding.stability is not None and finding.stability.rate_claim is None
    world = finding.observation.world
    assert world.failures == 1 and world.judged >= 4 and world.errors == 0
    assert 0 < world.interval_low < world.rate < world.interval_high < 1
    assert case.multiplicity is not None and case.multiplicity.worlds_tested == 2
    assert case.headline.startswith("Observed disagreement")
    from isitright.core.evidence import AuditReport, totals_of
    from isitright.packs.data.reports import markdown

    text = markdown(
        AuditReport(
            pack="data", kind="case", cases=[case], totals=totals_of([case]), elapsed_seconds=0
        )
    )
    assert "## Observed failures" in text and "95% Wilson interval" in text


def test_data_a_decided_rate_increase_is_the_stronger_grade_and_is_exported(
    data_audit: Any, tmp_path: Path
) -> None:
    from isitright.core.evidence import AuditReport, totals_of
    from isitright.packs.data.reports import export_eval_cases

    case = _live(data_audit, _FlakyDataAgent(random.Random(1), 0.0, 1.0), max_worlds=2)
    assert case.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert {f.evidence_grade.value for f in case.findings} == {"RATE_INCREASE"}
    report = AuditReport(
        pack="data", kind="case", cases=[case], totals=totals_of([case]), elapsed_seconds=0
    )
    assert len(export_eval_cases(report, tmp_path / "a")) == len(case.findings)


def test_data_export_leaves_observed_failures_out_unless_asked(
    data_audit: Any, tmp_path: Path
) -> None:
    from isitright.core.evidence import AuditReport, totals_of
    from isitright.packs.data.reports import export_eval_cases

    case = _live(data_audit, _WrongOnce(), max_worlds=2)
    report = AuditReport(
        pack="data", kind="case", cases=[case], totals=totals_of([case]), elapsed_seconds=0
    )
    assert export_eval_cases(report, tmp_path / "a") == []
    assert len(export_eval_cases(report, tmp_path / "b", include_observed=True)) == 1


def test_data_a_failing_baseline_can_be_audited_when_asked(data_audit: Any) -> None:
    agent = _FlakyDataAgent(random.Random(1), 1.0, 0.0)
    case = _live(data_audit, agent, allow_failing_baseline=True, max_worlds=2)
    # The baseline fails every run; the correct-answer worlds are judged and nothing fails there.
    assert case.divergence_status.value == "NOT_FOUND_WITHIN_BUDGET"
    assert case.findings == []
    judged = [w for w in case.worlds if w.id != "baseline" and w.counts.get("n")]
    assert judged and all(w.counts["met"] == w.counts["n"] for w in judged)


def test_data_cli_stops_on_a_failing_baseline_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pandas")
    from typer.testing import CliRunner

    from isitright.cli import app

    from .data_factories import make_task

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1]))
    args = [
        "data", "audit", str(make_task(tmp_path / "orders")),
        "--agent", "tests.data_agents:failing", "--trust-code", "--pass-env", "PYTHONPATH",
        "--baseline-runs", "2", "--max-worlds", "2", "--attempts", "12",
    ]  # fmt: skip
    stopped = CliRunner().invoke(app, [*args, "--output", str(tmp_path / "a")])
    assert stopped.exit_code == 2, stopped.output
    assert "baseline does not meet the expectation in every run" in stopped.output
    assert "--allow-failing-baseline" in stopped.output
    assert not (tmp_path / "a" / "report.json").exists()


# -- the research pack -------------------------------------------------------------------------


def _research_subject(a: Any, fail_calls: frozenset[int], world_always_bad: bool = False) -> Any:
    """The careful stand-in, with the numbered calls on mutated worlds (from 1, baseline runs not
    counted) citing a document that does not exist: a violated invariant."""
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject
    from isitright.packs.research.runs import Citation, Claim

    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()
    calls = [0]

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        on_base = world.fingerprint() == base
        if on_base:
            return run
        calls[0] += 1
        if world_always_bad or calls[0] in fail_calls:
            ghost = Claim(text="x", citations=[Citation(doc_id="no-such-document", quote="x")])
            report = run.report.model_copy(
                update={"claims": [ghost], "answer": run.report.answer or "x"}
            )
            run = run.model_copy(update={"report": report})
        return run

    return Subject(careful.label, True, execute)


def _research(fail_calls: frozenset[int], always: bool = False) -> tuple[Any, Any]:
    from .research_fixtures import audit

    a = audit(depth=1, runs=4, minimize=False, seed=11, max_runs=60)
    return a, a.check(_research_subject(a, fail_calls, always))


def test_research_one_failed_run_is_an_observed_failure(tmp_path: Path) -> None:
    from isitright.packs.research.replaying import cases_markdown, write_outputs

    a, case = _research(frozenset({2}))
    assert case.divergence_status.value == "OBSERVED_FAILURE", case.headline
    assert case.findings and {f.evidence_grade.value for f in case.findings} == {"OBSERVED_FAILURE"}
    assert case.multiplicity is not None and case.multiplicity.worlds_tested >= 2
    finding = case.findings[0]
    assert finding.observation.world.failures == 1
    text = cases_markdown(case)
    assert "## Observed failures" in text and "Evidence grade: OBSERVED_FAILURE" in text
    written = write_outputs(tmp_path / "o", case, a.artifacts, a.exports)
    assert not [p for p in written if p.name.endswith("eval-case.json")]
    assert all(f.export is None for f in case.findings)
    again = write_outputs(tmp_path / "p", case, a.artifacts, a.exports, include_observed=True)
    assert [p for p in again if p.name.endswith("eval-case.json")]


def test_research_a_subject_that_fails_every_run_in_the_worlds_is_a_rate_increase() -> None:
    _, case = _research(frozenset(), always=True)
    assert case.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    assert any(f.evidence_grade.value == "RATE_INCREASE" for f in case.findings)


def test_research_the_policy_gate_separates_the_grades() -> None:
    from isitright.core.evidence import LiveFailOn, policy_triggered

    _, observed = _research(frozenset({2}))
    _, decided = _research(frozenset(), always=True)
    gate = {
        LiveFailOn.NONE: (False, False),
        LiveFailOn.ANY_COUNTEREXAMPLE: (False, True),
        LiveFailOn.RATE_INCREASE: (False, True),
        LiveFailOn.OBSERVED_FAILURE: (True, True),
    }
    for policy, (on_observed, on_decided) in gate.items():
        assert policy_triggered(observed, policy) is on_observed, policy
        assert policy_triggered(decided, policy) is on_decided, policy


def test_research_an_agent_that_errors_in_every_world_is_inconclusive() -> None:
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject

    from .research_fixtures import audit

    a = audit(depth=1, runs=4, minimize=False, seed=11, max_runs=60)
    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        if world.fingerprint() == base:
            return run
        return run.model_copy(update={"status": "ERROR"})

    case = a.check(Subject(careful.label, True, execute))
    assert case.divergence_status.value == "INCONCLUSIVE", case.headline
    assert case.findings == []


# -- the shared pieces ---------------------------------------------------------------------------


def test_the_wilson_interval_matches_known_values() -> None:
    from isitright.core.stochastic import wilson_interval

    low, high = wilson_interval(5, 10)  # type: ignore[misc]
    assert (round(low, 4), round(high, 4)) == (0.2366, 0.7634)
    low, high = wilson_interval(0, 10)  # type: ignore[misc]
    assert low == 0.0 and round(high, 4) == 0.2775
    low, high = wilson_interval(10, 10)  # type: ignore[misc]
    assert high == pytest.approx(1.0) and round(low, 4) == 0.7225
    assert wilson_interval(0, 0) is None


def test_errored_and_unjudged_runs_are_beside_the_rate_not_in_it() -> None:
    from isitright.core.oracles import Outcome
    from isitright.core.stochastic import RunOutcome, rate_with_interval

    rate = rate_with_interval(
        [
            RunOutcome(Outcome.NOT_MET),
            RunOutcome(Outcome.MET),
            RunOutcome(None, error=True),
            RunOutcome(Outcome.CANNOT_JUDGE),
        ]
    )
    assert (rate.failures, rate.judged, rate.errors, rate.unjudged) == (1, 2, 1, 1)
    assert rate.rate == 0.5


def test_the_grade_follows_the_sequential_decision_only() -> None:
    from isitright.core.sequential import PairedSprt, SprtConfig
    from isitright.core.stochastic import EvidenceGrade, grade_of

    assert grade_of(None) is EvidenceGrade.OBSERVED_FAILURE
    test = PairedSprt(SprtConfig(min_pairs=4, max_pairs=20))
    for _ in range(30):
        test.add(False, True)
    assert grade_of(test) is EvidenceGrade.RATE_INCREASE
    quiet = PairedSprt(SprtConfig(min_pairs=4, max_pairs=20))
    for _ in range(4):
        quiet.add(False, False)
    assert grade_of(quiet) is EvidenceGrade.OBSERVED_FAILURE


def test_multiplicity_counts_only_worlds_with_a_judged_run() -> None:
    from isitright.core.oracles import Outcome
    from isitright.core.stochastic import EvidenceGrade, RunOutcome, multiplicity_of

    ok, bad = RunOutcome(Outcome.MET), RunOutcome(Outcome.NOT_MET)
    errored, unjudged = RunOutcome(None, error=True), RunOutcome(Outcome.CANNOT_JUDGE)
    m = multiplicity_of(
        [
            ([ok, ok], None),
            ([ok, bad], EvidenceGrade.OBSERVED_FAILURE),
            ([bad, bad], EvidenceGrade.RATE_INCREASE),
            ([errored, errored], None),
            ([unjudged], None),
        ],
        [ok, ok, ok, ok],
    )
    assert m.worlds_tested == 3
    assert (m.worlds_with_observed_failure, m.worlds_with_rate_increase) == (2, 1)
    assert m.expected_rate_increase_claims_under_no_effect == pytest.approx(0.15)
    assert m.expected_worlds_with_observed_failure_under_no_effect == 0.0  # baseline never failed
    assert m.decisions_corrected is False


def test_research_without_the_sequential_test_makes_no_rate_claim() -> None:
    """Eight failing runs of a world against eight passing baseline runs would give a fixed-sample
    comparison by run index a rate claim; no pairs were made, so none is made."""
    from .research_fixtures import audit

    a = audit(depth=1, runs=8, minimize=False, seed=11, max_runs=200, sequential=False)
    case = a.check(_research_subject(a, frozenset(), True))
    assert case.findings
    for finding in case.findings:
        assert finding.evidence_grade.value == "OBSERVED_FAILURE"
        assert finding.stability.rate_claim is None and "no rate claim" in finding.stability.note
    assert case.divergence_status.value == "OBSERVED_FAILURE"


# -- the report model refuses a grade or a status its evidence does not support ------------------


def _observed_case() -> Any:
    """An observation-only case built by hand: one finding with one judged failure, no pairs."""
    from isitright.core.evidence import DivergenceStatus, EvidenceGrade, Finding
    from isitright.core.stochastic import Observation, RateWithInterval

    from .factories import make_case

    base = make_case("c", DivergenceStatus.COUNTEREXAMPLE_FOUND).findings[0]
    finding = Finding.model_validate(
        {
            **base.model_dump(mode="json"),
            "evidence_grade": EvidenceGrade.OBSERVED_FAILURE.value,
            "built_from": {**base.built_from, "counts": base.world_fingerprint},
            "observation": Observation(
                world=RateWithInterval(failures=1, judged=4, errors=0, unjudged=0, rate=0.25)
            ).model_dump(mode="json"),
        }
    )
    return make_case("c", DivergenceStatus.OBSERVED_FAILURE, findings=[finding])


def _rate_case() -> Any:
    """A case whose one finding rests on a decided paired test (12 world-only discordant pairs,
    12 judged runs of the world and 12 of the baseline)."""
    from isitright.core.evidence import DivergenceStatus, EvidenceGrade, Finding
    from isitright.core.oracles import Outcome
    from isitright.core.sequential import PairedSprt, SprtConfig
    from isitright.core.stochastic import (
        RunOutcome,
        observation_of,
        stability_sequential,
    )

    from .factories import make_case

    bad, ok = RunOutcome(Outcome.NOT_MET), RunOutcome(Outcome.MET)
    test = PairedSprt(SprtConfig(min_pairs=4, max_pairs=20))
    for _ in range(12):
        test.add(False, True)
    assert test.decision.value == "RATE_INCREASE"
    stability = stability_sequential([ok] * 12, [bad] * 12, 4, test)
    base = make_case("c", DivergenceStatus.COUNTEREXAMPLE_FOUND).findings[0]
    finding = Finding.model_validate(
        {
            **base.model_dump(mode="json"),
            "evidence_grade": EvidenceGrade.RATE_INCREASE.value,
            "built_from": {**base.built_from, "counts": base.world_fingerprint},
            "stability": stability.model_dump(mode="json"),
            "observation": observation_of([bad] * 12, [ok] * 12).model_dump(mode="json"),
        }
    )
    return make_case("c", DivergenceStatus.COUNTEREXAMPLE_FOUND, findings=[finding])


def _tamper(case: Any, **changes: Any) -> dict[str, Any]:
    data = case.model_dump(mode="json")
    finding_changes = changes.pop("finding", {})
    data.update(changes)
    data["findings"] = [{**data["findings"][0], **finding_changes}]
    return data  # type: ignore[no-any-return]


def test_the_two_honest_cases_validate_and_round_trip() -> None:
    from isitright.core.evidence import CaseReport

    for case in (_observed_case(), _rate_case()):
        assert CaseReport.model_validate(case.model_dump(mode="json")) == case


def test_an_observation_cannot_be_serialized_as_a_counterexample_or_as_nothing() -> None:
    from pydantic import ValidationError

    from isitright.core.evidence import CaseReport

    case = _observed_case()
    for wrong in ("COUNTEREXAMPLE_FOUND", "NOT_FOUND_WITHIN_BUDGET", "INCONCLUSIVE"):
        with pytest.raises(ValidationError, match="status"):
            CaseReport.model_validate(_tamper(case, divergence_status=wrong))
    with pytest.raises(ValidationError, match="status"):  # a counterexample cannot be OBSERVED
        CaseReport.model_validate(_tamper(_rate_case(), divergence_status="OBSERVED_FAILURE"))


def test_a_higher_grade_and_status_cannot_be_claimed_over_unchanged_evidence() -> None:
    """Tamper the grade and the case status together; the sequential evidence still says no."""
    from pydantic import ValidationError

    from isitright.core.evidence import CaseReport

    tampered = _tamper(
        _observed_case(),
        divergence_status="COUNTEREXAMPLE_FOUND",
        finding={"evidence_grade": "RATE_INCREASE"},
    )
    with pytest.raises(ValidationError, match="sequential decision of RATE_INCREASE"):
        CaseReport.model_validate(tampered)


def test_a_rate_increase_needs_its_decision_its_claim_and_their_agreement() -> None:
    from pydantic import ValidationError

    from isitright.core.evidence import CaseReport

    case = _rate_case()
    data = case.model_dump(mode="json")
    stability = data["findings"][0]["stability"]
    undecided = {**stability, "sequential": {**stability["sequential"], "decision": "UNDECIDED"}}
    with pytest.raises(ValidationError, match="sequential decision of RATE_INCREASE"):
        CaseReport.model_validate(_tamper(case, finding={"stability": undecided}))
    with pytest.raises(ValidationError, match="sequential decision of RATE_INCREASE"):
        CaseReport.model_validate(
            _tamper(case, finding={"stability": {**stability, "sequential": None}})
        )
    with pytest.raises(ValidationError, match="needs the rate claim"):
        CaseReport.model_validate(
            _tamper(case, finding={"stability": {**stability, "rate_claim": None}})
        )
    claim = {**stability["rate_claim"], "paired_runs": stability["rate_claim"]["paired_runs"] + 1}
    with pytest.raises(ValidationError, match="disagree"):
        CaseReport.model_validate(
            _tamper(case, finding={"stability": {**stability, "rate_claim": claim}})
        )


def test_an_observed_failure_cannot_carry_a_decision_a_claim_or_no_failure() -> None:
    from pydantic import ValidationError

    from isitright.core.evidence import CaseReport

    # a decided test with the observed grade (and a status that follows the grade)
    decided = _tamper(
        _rate_case(),
        divergence_status="OBSERVED_FAILURE",
        finding={"evidence_grade": "OBSERVED_FAILURE"},
    )
    with pytest.raises(ValidationError, match="cannot carry a decided rate increase"):
        CaseReport.model_validate(decided)
    case = _observed_case()
    data = case.model_dump(mode="json")
    zero = {
        **data["findings"][0]["observation"],
        "world": {**data["findings"][0]["observation"]["world"], "failures": 0},
    }
    with pytest.raises(ValidationError, match="at least one judged failure"):
        CaseReport.model_validate(_tamper(case, finding={"observation": zero}))
    with pytest.raises(ValidationError, match="at least one judged failure"):
        CaseReport.model_validate(_tamper(case, finding={"observation": None}))


def test_ungraded_findings_need_no_sequential_evidence() -> None:
    from isitright.core.evidence import CaseReport, DivergenceStatus

    from .factories import make_case

    sql = make_case("legacy", DivergenceStatus.COUNTEREXAMPLE_FOUND)
    assert sql.findings[0].evidence_grade is None and sql.findings[0].stability is None
    assert CaseReport.model_validate(sql.model_dump(mode="json"))


def test_a_tampered_real_report_is_refused(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same, on a report an audit wrote."""
    from pydantic import ValidationError

    from isitright.core.evidence import AuditReport

    _observed_only_report(tmp_path, one_world, monkeypatch)
    data = json.loads((tmp_path / "out0" / "report.json").read_text(encoding="utf-8"))
    assert AuditReport.model_validate(data)
    case = data["cases"][0]
    case["divergence_status"] = "COUNTEREXAMPLE_FOUND"
    case["findings"][0]["evidence_grade"] = "RATE_INCREASE"
    with pytest.raises(ValidationError, match="sequential decision of RATE_INCREASE"):
        AuditReport.model_validate(data)


def test_cases_rank_domain_structural_other_counterexample_observed_inconclusive_nothing() -> None:
    from isitright.core.evidence import DivergenceStatus, rank_cases

    from .factories import make_case

    def named(case: Any, case_id: str) -> Any:
        return case.model_copy(update={"case_id": case_id})

    cx = DivergenceStatus.COUNTEREXAMPLE_FOUND
    cases = [
        make_case("nothing-1", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ()),
        named(_observed_case(), "observed-1"),
        make_case("inconclusive-1", DivergenceStatus.INCONCLUSIVE, ()),
        make_case("unassessed-1", cx, ()),  # a counterexample with NOT_ASSESSED validity
        make_case("structural-1", cx, ("STRUCTURAL",)),
        make_case("domain-1", cx, ("STRUCTURAL", "DOMAIN_VALIDATED")),
        named(_observed_case(), "observed-2"),
        make_case("unsupported-1", DivergenceStatus.UNSUPPORTED, ()),
        named(_rate_case(), "rate-unassessed-2"),  # a decided rate increase, tier STRUCTURAL
        make_case("unassessed-2", cx, ()),
        make_case("domain-2", cx, ("STRUCTURAL", "DOMAIN_VALIDATED")),
        make_case("nothing-2", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ()),
        make_case("structural-2", cx, ("STRUCTURAL",)),
        make_case("inconclusive-2", DivergenceStatus.INCONCLUSIVE, ()),
    ]
    assert cases[3].validity.status == "NOT_ASSESSED"
    ranked = [c.case_id for c in rank_cases(cases)]
    assert ranked == [
        "domain-1", "domain-2",  # 1. domain-validated counterexamples
        "structural-1", "rate-unassessed-2", "structural-2",  # 2. structural (a stable order)
        "unassessed-1", "unassessed-2",  # 3. other counterexamples, no tier assessed
        "observed-1", "observed-2",  # 4. observed failures
        "inconclusive-1", "unsupported-1", "inconclusive-2",  # 5. inconclusive and unsupported
        "nothing-1", "nothing-2",  # 6. nothing found
    ]  # fmt: skip
    assert _rate_case().validity.tiers == ["STRUCTURAL"]


def test_a_finding_is_graded_on_the_world_it_shows() -> None:
    """N5: the grade and the counts are those of the world shown, so the report no longer needs to
    say that they describe another world."""
    from isitright.core.evidence import describe_graded_findings

    case = _observed_case()
    text = "\n".join(describe_graded_findings(case))
    assert "describe the world the search ran" not in text and "until N5" not in text
    assert "was not itself tested by the paired test" not in text


def test_research_grades_the_world_it_shows() -> None:
    _, case = _research(frozenset({2}))
    assert case.findings
    for finding in case.findings:
        assert "graded_on_world" not in finding.divergence
        assert finding.world_fingerprint == finding.world_id
        assert finding.built_from["counts"] == finding.world_fingerprint


# -- the opt-in CI default (owner decision: `--fail-on` stays `none`) ----------------------------


def test_the_default_gate_is_none_on_every_live_command() -> None:
    import inspect

    from isitright.cli import AgentsFailOn, agents_run_command
    from isitright.core.evidence import LiveFailOn
    from isitright.packs.data.cli import audit_command as data_audit
    from isitright.packs.research.cli import check_command as research_check

    assert inspect.signature(agents_run_command).parameters["fail_on"].default is AgentsFailOn.NONE
    assert inspect.signature(research_check).parameters["fail_on"].default is LiveFailOn.NONE
    assert inspect.signature(data_audit).parameters["fail_on"].default is LiveFailOn.NONE


def test_omitting_fail_on_never_fails_the_build_even_on_a_decided_rate_increase(
    one_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from isitright.cli import app

    def invoke(decide: Decide, name: str, *policy: str) -> Any:
        _scripted_agent(monkeypatch, one_world, decide)
        return CliRunner().invoke(
            app,
            [
                "agents", "run", "--scenario", SHOP_REF, "--agent-command", "fake", "--trust-code",
                "--world", one_world["worlds"][0], "--attempts", "2000",
                "--output-dir", str(tmp_path / name), *policy,
            ],
        )  # fmt: skip

    observed = invoke(_fails_once(), "o")
    assert observed.exit_code == 0 and "Status: OBSERVED_FAILURE" in observed.output
    decided = invoke(_always_bad_in_worlds, "d")
    assert decided.exit_code == 0 and "Status: COUNTEREXAMPLE_FOUND" in decided.output
    # The recommended opt-in gate trips only on the decided one; the stricter one on both.
    assert invoke(_fails_once(), "o2", "--fail-on", "rate-increase").exit_code == 0
    assert invoke(_always_bad_in_worlds, "d2", "--fail-on", "rate-increase").exit_code == 3
    assert invoke(_fails_once(), "o3", "--fail-on", "observed-failure").exit_code == 3


def test_omitting_fail_on_never_fails_the_build_for_research(tmp_path: Path) -> None:
    from .test_research_cli import base_args, invoke

    found = invoke(*base_args(tmp_path / "a"), "--stand-in", "credulous", "--depth", "1")
    assert found.exit_code == 0, found.output
    assert "Counterexample found" in found.output
    gated = invoke(
        *base_args(tmp_path / "b"), "--stand-in", "credulous", "--depth", "1",
        "--fail-on", "rate-increase",
    )  # fmt: skip
    # A deterministic subject's counterexample is not a rate increase: only the policies that name
    # counterexamples, not the rate gate, trip on it.
    assert gated.exit_code == 0, gated.output
    anything = invoke(
        *base_args(tmp_path / "c"), "--stand-in", "credulous", "--depth", "1",
        "--fail-on", "any-counterexample",
    )  # fmt: skip
    assert anything.exit_code == 3, anything.output
    strict = invoke(
        *base_args(tmp_path / "d"), "--stand-in", "credulous", "--depth", "1",
        "--fail-on", "observed-failure",
    )  # fmt: skip
    assert strict.exit_code == 3, strict.output


def test_each_ci_policy_on_each_kind_of_evidence() -> None:
    """Three kinds of finding (a decided rate increase, an observation, an ungraded counterexample
    such as a deterministic or SQL one) against every policy, through `policy_triggered`."""
    from isitright.core.evidence import DivergenceStatus, FailOn, LiveFailOn, policy_triggered

    from .factories import make_case

    ungraded = make_case("u", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL",))
    domain = make_case(
        "d", DivergenceStatus.COUNTEREXAMPLE_FOUND, ("STRUCTURAL", "DOMAIN_VALIDATED")
    )
    assert ungraded.findings[0].evidence_grade is None
    kinds = {"rate": _rate_case(), "observed": _observed_case(), "ungraded": ungraded}
    expected = {  # policy -> (rate, observed, ungraded)
        "none": (False, False, False),
        "rate-increase": (True, False, False),
        "any-counterexample": (True, False, True),
        "observed-failure": (True, True, True),
    }
    for policy, (rate, observed, other) in expected.items():
        got = tuple(policy_triggered(kinds[k], LiveFailOn(policy)) for k in kinds)
        assert got == (rate, observed, other), policy
    # the policies that SQL has keep their meaning
    assert policy_triggered(ungraded, FailOn.ANY_COUNTEREXAMPLE) is True
    assert policy_triggered(ungraded, FailOn.DOMAIN_COUNTEREXAMPLE) is False
    assert policy_triggered(domain, FailOn.DOMAIN_COUNTEREXAMPLE) is True
    assert policy_triggered(domain, FailOn.NONE) is False
    # a case that found nothing never trips any policy
    quiet = make_case("q", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, ())
    assert not any(policy_triggered(quiet, LiveFailOn(p)) for p in expected)


def test_an_emulated_unverified_counterexample_trips_no_policy() -> None:
    from isitright.core.evidence import (
        DivergenceStatus,
        FidelityRecord,
        LiveFailOn,
        policy_triggered,
    )

    from .factories import make_case

    emulated = make_case(
        "e",
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
        ("STRUCTURAL", "DOMAIN_VALIDATED"),
        execution_fidelity=FidelityRecord(found_on="EMULATED", engine="duckdb 1"),
    )
    assert not any(policy_triggered(emulated, LiveFailOn(p)) for p in (
        "rate-increase", "any-counterexample", "observed-failure", "domain-counterexample"
    ))  # fmt: skip
    verified = emulated.model_copy(
        update={
            "execution_fidelity": FidelityRecord(
                found_on="EMULATED", verified_on="NATIVE_ISOLATED", engine="duckdb 1"
            )
        }
    )
    assert policy_triggered(verified, LiveFailOn("any-counterexample")) is True
