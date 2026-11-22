"""Audit an agent: baseline runs, then runs in each generated (or hand-written) world.

For every world the report keeps apart whether the agent and the oracle disagree, how valid the
world is, how faithful the host is, what the oracle was and whether it could judge, how many runs
there were against the baseline, and (always undetermined) who is at fault.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from isitright import __version__
from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    ControlsRecord,
    DivergenceStatus,
    EvalCase,
    EvidenceGrade,
    FidelityRecord,
    Finding,
    HintUse,
    MutationRecord,
    OracleRecord,
    ScreeningRecord,
    ScreeningSummary,
    SearchRecord,
    ValidityRecord,
    WorldRecord,
    describe_graded_findings,
    safe_detail,
    safe_name,
    totals_of,
)
from isitright.core.minimize import NoisyMinimization, minimize_path_noisy
from isitright.core.mutations import World
from isitright.core.oracles import Outcome, Role, controls_status
from isitright.core.paths import contained_path, replay_placeholder
from isitright.core.search import Progress
from isitright.core.sequential import PairedSprt, RateSprtConfig, SprtConfig
from isitright.core.stochastic import (
    DEFAULT_K,
    Budget,
    RunOutcome,
    Stability,
    SubjectRunner,
    count,
    grade_of,
    is_bad,
    is_judged,
    multiplicity_of,
    observation_of,
    stability_counts_only,
    stability_sequential,
)
from isitright.core.world import diff_states, sha256_text
from isitright.packs.mcp.generate import GeneratedWorld, generate_worlds
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    FixedWorld,
    Interference,
    McpScenario,
    ScenarioError,
    absolute_reference,
    load_scenario,
    with_hints_file,
)
from isitright.packs.mcp.oracle import EvaluationError, Reference, judge_run, reference_outcome
from isitright.packs.mcp.runner import (
    AgentRun,
    AgentsInputError,
    collect,
    harness_identity,
    read_trace,
    record_mcp_config,
    run_agent,
    split_command,
    write_mcp_config,
)
from isitright.packs.mcp.screening import (
    Ranking,
    Screened,
    ScreeningClass,
    StoppingRules,
    StopState,
    eligible,
    rank,
    screen_all,
)
from isitright.packs.mcp.serve import world_of

WorldSource = Literal["generated", "fixed", "all"]

__all__ = ["AgentsInputError", "RunWorld", "prepare_worlds", "run_scenario", "write_report"]

DEFAULT_MAX_WORLDS = 50
"""A safety rail on generated worlds, not a recommendation: set a money, run or time budget."""
DEFAULT_MAX_TRIALS = 20
GENERATION_REPORT_EVERY = 100
"""Candidates visited between two progress reports while the worlds are generated."""
"""The most paired runs the sequential test may use on one world."""
NOT_RUN_RECORDS = 300
HINT_WORLDS_LISTED = 20
"""Not-run worlds listed one by one in the report; the rest are counted by reason."""


@dataclass
class RunWorld:
    """One world to run: the core world, its provenance and what the oracle says about it."""

    id: str
    world: World
    description: str
    reference: Reference
    validity: ValidityRecord
    interferences: tuple[Interference, ...] = ()
    fixed: FixedWorld | None = None
    generated: GeneratedWorld | None = None
    baseline: bool = False

    @property
    def role(self) -> Role:
        return Role.BASELINE if self.baseline else self.reference.role

    @property
    def runnable(self) -> bool:
        return self.validity.status != "INVALID"


def prepare_worlds(
    scenario: McpScenario,
    source: WorldSource,
    *,
    attempts: int,
    seed: int,
    only: list[str] | None = None,
    progress: Progress | None = None,
) -> tuple[list[RunWorld], dict[str, Any]]:
    """The baseline, then hand-written and/or generated worlds, each with its reference.

    Every valid generated world is returned; which ones run, and in what order, is decided later
    by screening and the stopping rules.
    """
    base = World(scenario.base)
    base_reference = reference_outcome(scenario, base)
    worlds = [
        RunWorld(
            "baseline",
            base,
            "the unmutated world",
            base_reference,
            ValidityRecord(status="VALID", tiers=["STRUCTURAL", "DOMAIN_VALIDATED"]),
            baseline=True,
        )
    ]
    accounting: dict[str, Any] = {}
    if source in ("fixed", "all"):
        for fixed in scenario.fixed_worlds:
            world, interferences = world_of(scenario, fixed)
            problems: list[str] = []
            if fixed.validate is None:
                validity = ValidityRecord(status="NOT_ASSESSED")
            else:
                try:
                    problems = fixed.validate(fixed.build())
                except Exception as error:
                    problems = [f"validation raised: {error}"]
                validity = (
                    ValidityRecord(status="INVALID", problems=problems)
                    if problems
                    else ValidityRecord(status="VALID", tiers=["STRUCTURAL", "DOMAIN_VALIDATED"])
                )
            reference = reference_outcome(scenario, world, interferences)
            worlds.append(
                RunWorld(
                    fixed.id, world, fixed.description, reference, validity, interferences, fixed
                )
            )
    if source in ("generated", "all"):
        generated, result = generate_worlds(
            scenario, attempts=attempts, seed=seed, progress=progress
        )
        accounting = result.accounting()
        accounting["generated_total"] = len(generated)
        for g in generated:
            tiers = g.tiers
            worlds.append(
                RunWorld(
                    g.id,
                    g.world,
                    g.description,
                    g.reference,
                    ValidityRecord(
                        status="VALID",
                        tiers=tiers,
                        unobservable=not g.observable,
                        notes=g.notes,
                    ),
                    generated=g,
                )
            )
    if only is not None:
        keep = set(only) | {"baseline"}
        worlds = [w for w in worlds if w.id in keep]
    return worlds, accounting


@dataclass
class WorldResult:
    world: RunWorld
    outcomes: list[RunOutcome] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    example: AgentRun | None = None
    violations: list[tuple[str, str]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    sequential: PairedSprt | None = None
    paired_baseline: list[RunOutcome] = field(default_factory=list)
    """The fresh baseline runs this world's pairs were made with (empty when not paired)."""
    minimization: NoisyMinimization | None = None


@dataclass
class NotRun:
    """A world the run did not reach. It is reported as not run, never as passing."""

    world: RunWorld
    reason: str
    screened: Screened | None = None
    rank: int | None = None


@dataclass
class RunTarget:
    """What an agent run is made on: a world, and the result that collects the runs made on it."""

    rw: RunWorld
    result: WorldResult


@dataclass
class _Launched:
    """One agent run before it is judged: where it ran and what it left behind."""

    run: AgentRun
    status: str
    exit_code: int | None
    duration: float
    relative: str
    seed: int
    trial: int


class _AgentCommand:
    """The agent command as `SubjectRunner` runs it: one process per run, in its own directory."""

    def __init__(
        self,
        scenario: McpScenario,
        argv: list[str],
        scenario_ref: str,
        recorded_ref: str,
        output_dir: Path,
        timeout: float,
        harness: tuple[str | None, str | None],
    ) -> None:
        self.scenario = scenario
        self.argv = argv
        self.scenario_ref = scenario_ref
        self.recorded_ref = recorded_ref
        self.output_dir = output_dir
        self.timeout = timeout
        self.harness = harness
        self.trials: dict[str, int] = {}
        """Runs made so far per world id: the baseline's runs share one numbering."""

    def execute(self, target: RunTarget, seed: int, /) -> _Launched:
        rw = target.rw
        trial = self.trials[rw.id] = self.trials.get(rw.id, 0) + 1
        relative = f"runs/{rw.id}/{trial}"
        run_dir = self.output_dir / relative
        run_dir.mkdir(parents=True)
        (run_dir / "task.txt").write_text(self.scenario.task, encoding="utf-8")
        world_file = run_dir / "world.json"
        world_file.write_text(json.dumps(rw.world.to_json(), sort_keys=True), encoding="utf-8")
        mcp_config = write_mcp_config(
            run_dir,
            self.scenario_ref,
            world_file=None if rw.fixed is not None else world_file,
            fixed_id=rw.fixed.id if rw.fixed is not None else None,
        )
        started = time.monotonic()
        status, exit_code = run_agent(
            self.argv, run_dir, mcp_config, run_dir / "task.txt", rw.id, self.timeout
        )
        duration = time.monotonic() - started
        record_mcp_config(mcp_config, self.output_dir, scenario_ref=self.recorded_ref)
        fallback = self.scenario.layout.to_service(rw.world.state)
        run = collect(run_dir, status, round(duration, 3), self.harness, fallback)
        return _Launched(run, status, exit_code, duration, relative, seed, trial)


def _judge_launched(
    scenario: McpScenario,
    require_cost: bool,
    progress: Callable[[str, str], None] | None,
) -> Callable[[RunTarget, _Launched, str], RunOutcome]:
    """The judging half of a run: oracle verdict, the run's record in its world's result."""

    def judge(target: RunTarget, launched: _Launched, tag: str) -> RunOutcome:
        rw, result, run, status = target.rw, target.result, launched.run, launched.status
        if require_cost and status == "COMPLETED" and "money" not in run.extra:
            raise AgentsInputError(
                "a money budget needs the agent to report what each run cost, and this agent did "
                "not: write a transcript.json whose usage entries each have a 'cost' (see "
                "https://docs.isitright.ai/agents/run-your-agent/), "
                "or bound the run with --max-runs or --max-seconds instead"
            )
        try:
            judgement = judge_run(scenario, rw.reference, run.before, run.after, run.trace)
        except EvaluationError as error:
            raise AgentsInputError(str(error)) from error
        calls = [e for e in run.trace if e["name"] != WORLD_CHANGE]
        writes = sum(
            1 for e in calls if (tool := scenario.tool(e["name"])) is not None and tool.writes
        )
        completed = status == "COMPLETED"
        expectation_met: bool | None = None
        if completed and rw.fixed is not None and rw.fixed.expectation is not None:
            expectation_met = bool(
                rw.fixed.expectation.met(
                    copy.deepcopy(run.before), copy.deepcopy(run.after), copy.deepcopy(run.trace)
                )
            )
        outcome = RunOutcome(
            judgement.outcome if completed else None,
            violated=bool(judgement.violations),
            error=not completed,
            cost=run.record.cost,
        )
        result.runs.append(
            {
                "world_id": rw.id,
                "trial": launched.trial,
                "seed": launched.seed,
                "run_status": status,
                "exit_code": launched.exit_code,
                "duration_seconds": round(launched.duration, 3),
                "tool_calls": len(calls),
                "write_calls": writes,
                "violations": [{"invariant": n, "message": m} for n, m in judgement.violations],
                "outcome": judgement.outcome.value if completed else None,
                "run_dir": launched.relative,
                "fixed_id": rw.fixed.id if rw.fixed is not None else None,
                "expectation_met": expectation_met,
                "cost": run.record.cost.money,
                **{k: v for k, v in run.extra.items() if k != "money"},
            }
        )
        result.outcomes.append(outcome)
        if completed:
            result.violations.extend(judgement.violations)
            if (
                judgement.violations or judgement.outcome is Outcome.NOT_MET
            ) and result.example is None:
                result.example = run
                result.messages = judgement.messages
        if progress is not None:
            progress(rw.id, _marker(outcome))
        return outcome

    return judge


def run_scenario(
    *,
    scenario_ref: str,
    agent_command: str,
    output_dir: Path,
    worlds: WorldSource = "generated",
    k: int = DEFAULT_K,
    trials: int | None = None,
    baseline_trials: int | None = None,
    timeout_seconds: float = 300.0,
    trust_code: bool = False,
    seed: int = 0,
    attempts: int = 20_000,
    max_worlds: int | None = DEFAULT_MAX_WORLDS,
    only: list[str] | None = None,
    budget: Budget | None = None,
    ranking: Ranking = "diverse",
    rules: StoppingRules | None = None,
    sequential: bool = True,
    sprt: SprtConfig | None = None,
    max_trials: int = DEFAULT_MAX_TRIALS,
    minimize: bool = False,
    minimize_max_runs: int = 200,
    hints_file: Path | None = None,
    progress: Callable[[str, str], None] | None = None,
    generation_progress: Callable[[int, int, int], None] | None = None,
) -> AuditReport:
    """Run ``agent_command`` on the baseline, then on the generated worlds in ranked order.

    The baseline runs first. Its recorded trace screens every candidate world without the agent
    (`isitright.packs.mcp.screening`), which orders the live runs. Each world is run in pairs with
    the baseline until a sequential test decides or the run cap ``max_trials`` is reached; a stratum
    stops after ``rules.stratum_patience`` worlds without a finding, and the run after
    ``rules.run_patience`` consecutive worlds that add nothing. Worlds not reached are reported as
    not run, with the reason. ``progress(world_id, marker)`` is called after every agent run with
    one character: ``.`` as expected, ``V`` invariant violated, ``N`` expected behavior not met,
    ``?`` could not be judged, ``E`` the run did not complete. ``baseline_trials`` sets the
    baseline's run count when it should differ from ``trials`` (default: the same).
    """
    if not trust_code:
        raise AgentsInputError("running a scenario executes its code; pass trust_code=True")
    if importlib.util.find_spec("mcp") is None:
        raise AgentsInputError("the MCP SDK is not installed; run: pip install 'isitright[mcp]'")
    k = trials if trials is not None else k
    baseline_k = baseline_trials if baseline_trials is not None else k
    if k < 1 or baseline_k < 1 or timeout_seconds <= 0 or max_trials < 1:
        raise AgentsInputError("trials and max_trials must be at least 1 and the timeout positive")
    if output_dir.exists():
        raise AgentsInputError("output directory already exists; choose a new directory")
    reference_text = absolute_reference(scenario_ref)
    try:
        scenario = load_scenario(reference_text)
    except ScenarioError as error:
        raise AgentsInputError(str(error)) from error
    if hints_file is not None:
        try:
            scenario = with_hints_file(scenario, hints_file)
        except ScenarioError as error:
            raise AgentsInputError(str(error)) from error
    argv = split_command(agent_command)
    budget = budget or Budget()
    rules = rules or StoppingRules()
    config = sprt or SprtConfig(min_pairs=k, max_pairs=max(k, max_trials))
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True)
    harness = harness_identity(argv)
    started = time.monotonic()
    visited = valid = 0

    def count_candidate(event: str) -> None:
        nonlocal visited, valid
        visited += 1
        valid += event != "rejected"
        if generation_progress is not None and visited % GENERATION_REPORT_EVERY == 0:
            generation_progress(visited, valid, attempts)

    prepared, accounting = prepare_worlds(
        scenario, worlds, attempts=attempts, seed=seed, only=only, progress=count_candidate
    )
    if only is not None:
        unknown = sorted(set(only) - {rw.id for rw in prepared})
        if unknown:
            raise AgentsInputError(
                f"no such world: {', '.join(unknown)} (generated ids come from the mutations, so "
                "the attempt budget must be large enough to reach the world)"
            )
    results: list[WorldResult] = []
    not_run: list[NotRun] = []
    extra: list[WorldResult] = []
    baseline_rw = prepared[0]
    base = WorldResult(baseline_rw)
    results.append(base)
    anything_to_audit = any(rw.runnable and not rw.baseline for rw in prepared)

    runner: SubjectRunner[RunTarget, _Launched] = SubjectRunner(
        _AgentCommand(
            scenario,
            argv,
            reference_text,
            scenario_ref,  # recorded as typed; the absolute form above launched the servers
            output_dir,
            timeout_seconds,
            harness,
        ),
        _judge_launched(scenario, budget.money is not None, progress),
        budget,
        seed=seed,
    )
    base_target = RunTarget(baseline_rw, base)
    comparison = RunTarget(baseline_rw, WorldResult(baseline_rw))
    """Fresh baseline runs made for the pairs; `base` keeps the runs made before the search."""
    extra.append(comparison.result)
    if anything_to_audit:
        runner.run_repeated(base_target, baseline_k, "baseline")
    generated = [rw for rw in prepared if rw.generated is not None]
    fixed = [rw for rw in prepared if rw.fixed is not None]
    trace_dir, trace = _baseline_trace(base, output_dir)
    gen_worlds = [rw.generated for rw in generated if rw.generated is not None]
    screens = screen_all(scenario, gen_worlds, trace)
    by_id = {rw.id: rw for rw in generated}
    ranked = [by_id[w.id] for w in rank(gen_worlds, screens, mode=ranking, seed=seed)]
    rail = max_worlds if only is None else None
    to_run = ranked if rail is None else ranked[:rail]
    ranks = {rw.id: i + 1 for i, rw in enumerate(ranked)}
    stop = StopState(rules, [rw.generated for rw in ranked if rw.generated is not None])
    if only is not None:
        # A world named by id is always run, even one screening or the oracle would leave out.
        keep = set(only)
        fixed = [rw for rw in fixed if rw.id in keep]
        to_run = [rw for rw in generated if rw.id in keep]

    def skip(rw: RunWorld, reason: str) -> None:
        not_run.append(NotRun(rw, reason, screens.get(rw.id), ranks.get(rw.id)))

    considered = {rw.id for rw in ranked} | {rw.id for rw in fixed} | {rw.id for rw in to_run}
    for rw in prepared:
        if rw.baseline or rw.id in considered or (only is not None and rw.id not in only):
            continue
        skip(rw, _ineligible_reason(rw))
    for rw in [*fixed, *to_run]:
        result = WorldResult(rw)
        if not rw.runnable or not anything_to_audit:
            results.append(result)
            continue
        reason = stop.skip_reason(rw.generated) if rw.generated is not None else None
        if reason is None and not budget.can_run():
            reason = f"{budget.exhausted} budget exhausted"
            stop.record_budget(budget.exhausted)
        if reason is not None:
            skip(rw, reason)
            continue
        results.append(result)
        _run_world(runner, RunTarget(rw, result), base_target, comparison, config, k, sequential)
        found = any(is_bad(o) for o in result.outcomes)
        if rw.generated is not None:
            stop.record(rw.generated, found)
        if minimize and found and rw.generated is not None and len(rw.world.path) > 1:
            result.minimization = _minimize_world(
                scenario,
                rw,
                base,
                runner,
                extra,
                min(minimize_max_runs, _runs_left(budget)),
            )
    if rail is not None:
        for rw in ranked[len(to_run) :]:
            skip(rw, f"safety rail: --max-worlds {rail} reached")
    report = build_report(
        scenario,
        scenario_ref,  # as the user typed it; the absolute form above only launches the servers
        agent_command,
        k,
        results,
        accounting,
        budget,
        round(time.monotonic() - started, 3),
        context=ReportContext(
            not_run=not_run,
            screens=screens,
            ranking=ranking,
            ranks=ranks,
            stop=stop,
            trace_dir=trace_dir,
            generated=generated,
            sprt=config if sequential else None,
            seed=seed,
            extra_runs=[run for e in extra for run in e.runs],
        ),
    )
    write_report(report, output_dir)
    return report


def _marker(outcome: RunOutcome) -> str:
    if outcome.error:
        return "E"
    if outcome.violated:
        return "V"
    if outcome.outcome is Outcome.NOT_MET:
        return "N"
    if outcome.outcome is Outcome.CANNOT_JUDGE:
        return "?"
    return "."


def _runs_left(budget: Budget) -> int:
    return budget.runs - budget.spent_runs if budget.runs is not None else 10**9


def _minimize_world(
    scenario: McpScenario,
    rw: RunWorld,
    base: WorldResult,
    runner: SubjectRunner[RunTarget, _Launched],
    extra: list[WorldResult],
    max_runs: int,
) -> NoisyMinimization:
    """Minimize the mutation path of a world that failed, judging each subset by repeated runs."""
    baseline_bad = sum(is_bad(o) for o in base.outcomes)
    n = max(len(base.outcomes), 1)
    reference = min(0.5, max(0.05, baseline_bad / n))
    config = RateSprtConfig(reference=reference, effect=min(0.95, reference + 0.45))
    results: dict[str, RunTarget] = {}

    def run(world: World) -> bool:
        label = "+".join(str(i) for i, m in enumerate(rw.world.path) if m in world.path)
        sub_id = f"{rw.id}.min_{label or 'none'}"
        if sub_id not in results:
            step_result = WorldResult(rw)
            results[sub_id] = RunTarget(
                RunWorld(
                    sub_id,
                    world,
                    "minimization step: "
                    + ("; ".join(m.description for m in world.path) or "none"),
                    reference_outcome(scenario, world),
                    ValidityRecord(status="NOT_ASSESSED"),
                ),
                step_result,
            )
            extra.append(step_result)
        executed = runner.run(results[sub_id], "minimize", after_search=True)
        if executed is None:
            return False  # the budget is spent: not shown to reproduce, so the step is kept
        return is_bad(executed.outcome)

    result = minimize_path_noisy(
        World(scenario.base), list(rw.world.path), run, config=config, max_runs=max_runs
    )
    return result


def _ineligible_reason(rw: RunWorld) -> str:
    g = rw.generated
    if g is None:
        return "not selected"
    if g.role is Role.UNJUDGEABLE:
        return f"the oracle cannot judge this world: {g.role_basis}"
    if not g.observable:
        return "the change is unobservable to the agent (a tool-contract finding, not an agent one)"
    return "not selected"


def _baseline_trace(
    base: WorldResult, output_dir: Path
) -> tuple[str | None, list[dict[str, Any]] | None]:
    """The first completed baseline run's recorded calls, or None when there is none to replay."""
    for run in base.runs:
        if run["run_status"] != "COMPLETED":
            continue
        directory = contained_path(output_dir, str(run["run_dir"]), what="run directory")
        if (directory / "state_before.json").is_file():
            return run["run_dir"], [dict(e) for e in read_trace(directory / "trace.jsonl")]
    return None, None


def _run_world(
    runner: SubjectRunner[RunTarget, _Launched],
    target: RunTarget,
    base: RunTarget,
    comparison: RunTarget,
    config: SprtConfig,
    k: int,
    sequential: bool,
) -> None:
    """Run one world: k runs. When the test is sequential and one of them failed, pairs with fresh
    baseline runs follow until the test decides; a world that did not fail costs no baseline run."""
    if not sequential or all(o.error for o in base.result.outcomes):  # no baseline run to pair with
        runner.run_repeated(target, k, "search")
        return
    staged = runner.run_staged(target, comparison, config, k)
    if staged.paired is not None:
        target.result.sequential = staged.paired.test
        target.result.paired_baseline = staged.paired.baseline_outcomes


def _oracle_records(scenario: McpScenario, example: WorldResult | None) -> list[OracleRecord]:
    records = [
        OracleRecord(
            name=i.name,
            kind="INVARIANT",
            description=i.description,
            limits=["checked on every run; says nothing about runs that did not complete"],
        )
        for i in scenario.oracle.invariants
    ]
    records.append(
        OracleRecord(
            name=scenario.oracle.name,
            kind="REFERENCE_PROGRAM",
            description=scenario.oracle.description,
            limits=list(scenario.oracle.assumptions)[:6],
        )
    )
    return records


@dataclass
class ReportContext:
    """What the run decided besides the runs: not-run worlds, screening, ranking, stopping."""

    not_run: list[NotRun] = field(default_factory=list)
    screens: dict[str, Screened] = field(default_factory=dict)
    ranking: str = "diverse"
    ranks: dict[str, int] = field(default_factory=dict)
    stop: StopState | None = None
    trace_dir: str | None = None
    generated: list[RunWorld] = field(default_factory=list)
    sprt: SprtConfig | None = None
    seed: int = 0
    extra_runs: list[dict[str, Any]] = field(default_factory=list)
    """Runs made to minimize a path: kept for replay, not worlds of the report."""


def build_report(
    scenario: McpScenario,
    scenario_ref: str,
    agent_command: str,
    k: int,
    results: list[WorldResult],
    accounting: dict[str, Any],
    budget: Budget,
    elapsed: float,
    context: ReportContext | None = None,
) -> AuditReport:
    context = context or ReportContext()
    baseline = next(r for r in results if r.world.baseline)
    baseline_outcomes = baseline.outcomes or None
    runnable = [r for r in results if r.world.runnable and not r.world.baseline]
    findings: list[Finding] = []
    world_records: list[WorldRecord] = []
    for r in results:
        rw = r.world
        outcomes = r.outcomes
        reference_outcome_value = (
            Outcome.CANNOT_JUDGE if rw.reference.role is Role.UNJUDGEABLE else None
        )
        counts = count(outcomes)
        world_records.append(
            WorldRecord(
                id=rw.id,
                role=rw.role.value,
                description=rw.description,
                validity=rw.validity,
                oracle_outcome=(
                    reference_outcome_value.value if reference_outcome_value else _summary(outcomes)
                ),
                role_basis=rw.reference.basis
                + (f"; author's label: {rw.fixed.role}" if rw.fixed is not None else ""),
                counts=counts.model_dump(),
                mutation_path=_path(rw.world),
                screening=_screening_record(context, rw.id),
                run_status="RUN" if outcomes or rw.baseline or not rw.runnable else "NOT_RUN",
                not_run_reason=None
                if outcomes or rw.baseline or not rw.runnable
                else "no run completed",
            )
        )
        if rw.baseline or not outcomes:
            continue
        bad = [o for o in outcomes if o.violated or o.outcome is Outcome.NOT_MET]
        if not bad or r.example is None:
            continue
        violated = sorted({n for n, _ in r.violations})
        oracles = [
            OracleRecord(
                name=n,
                kind="INVARIANT",
                outcome="NOT_MET",
                description=next(
                    (i.description for i in scenario.oracle.invariants if i.name == n), ""
                ),
            )
            for n in violated
        ]
        reached = any(o.outcome is Outcome.NOT_MET for o in outcomes)
        oracles.append(
            OracleRecord(
                name=scenario.oracle.name,
                kind="REFERENCE_PROGRAM",
                outcome="NOT_MET" if reached else "MET",
                description=scenario.oracle.description,
            )
        )
        findings.append(
            Finding(
                finding_id=f"{scenario.id}:{rw.id}",
                world_id=rw.id,
                validity=rw.validity,
                oracles=oracles,
                stability=(
                    stability_sequential(r.paired_baseline, outcomes, k, r.sequential)
                    if r.sequential is not None
                    else stability_counts_only(baseline_outcomes, outcomes, k)
                ),
                evidence_grade=grade_of(r.sequential),
                observation=observation_of(outcomes, r.paired_baseline),
                world_diff=diff_states(scenario.base, rw.world.state),
                mutation_path=(
                    _mutation_records(r.minimization.path)
                    if r.minimization is not None and r.minimization.minimal
                    else _path(rw.world)
                ),
                minimization=_minimization_record(r.minimization, len(rw.world.path)),
                divergence={
                    "role": rw.role.value,
                    "example_run_dir": next(
                        run["run_dir"]
                        for run in r.runs
                        if run["violations"] or run["outcome"] == "NOT_MET"
                    ),
                    "messages": r.messages,
                    "violations": [{"invariant": n, "message": m} for n, m in r.violations[:5]],
                    "runs_affected": len(bad),
                    "runs_evaluated": len(outcomes),
                    "world_changes_in_trace": sum(
                        1 for e in r.example.trace if e["name"] == WORLD_CHANGE
                    ),
                },
                fidelity=FidelityRecord(found_on=scenario.fidelity.value),
                headline=_finding_headline(violated, reached, len(bad), len(outcomes), rw.id),
            )
        )
    world_records.extend(_not_run_records(context))
    completed = sum(1 for r in results for o in r.outcomes if not o.error)
    judged_mutated = sum(is_judged(o) for r in runnable for o in r.outcomes)
    rate_findings = [f for f in findings if f.evidence_grade is EvidenceGrade.RATE_INCREASE]
    status = (
        DivergenceStatus.UNSUPPORTED
        if not runnable and not any(n.world.runnable for n in context.not_run)
        else DivergenceStatus.COUNTEREXAMPLE_FOUND
        if rate_findings
        else DivergenceStatus.OBSERVED_FAILURE
        if findings
        else DivergenceStatus.INCONCLUSIVE
        if judged_mutated == 0
        else DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    )
    grades = {f.world_id: f.evidence_grade for f in findings}
    multiplicity = multiplicity_of(
        [(r.outcomes, grades.get(r.world.id)) for r in runnable],
        [*(baseline_outcomes or []), *(o for r in runnable for o in r.paired_baseline)],
    )
    pairs = [(r.world.role, [o.outcome for o in r.outcomes if o.outcome]) for r in results]
    controls_state, controls_detail = controls_status(
        [(role, [o for o in outs if o is not None]) for role, outs in pairs]
    )
    tiers_sets = [set(r.world.validity.tiers) for r in results if r.world.runnable]
    common = set.intersection(*tiers_sets) if tiers_sets else set()
    unassessed = [
        r.world.id
        for r in results
        if r.world.runnable and r.world.validity.status == "NOT_ASSESSED"
    ]
    if not tiers_sets:
        validity = ValidityRecord(status="INVALID")
    elif unassessed:
        validity = ValidityRecord(
            status="NOT_ASSESSED",
            notes=[
                f"{len(unassessed)} world(s) ran with no validator ({', '.join(unassessed[:5])}"
                f"{', ...' if len(unassessed) > 5 else ''}): no validity tier is claimed for the "
                "case; each world's own validity is in `worlds` and `findings`"
            ],
        )
    else:
        validity = ValidityRecord(
            status="VALID",
            tiers=[t for t in ("STRUCTURAL", "DOMAIN_VALIDATED") if t in common],
        )
    runs = [run for r in results for run in r.runs] + context.extra_runs
    subjects = {
        json.dumps(run.get("subject"), sort_keys=True) for run in runs if run.get("subject")
    }
    selection = _selection(accounting, results, context)
    search_record = _search_record(accounting, budget, len(runs), context, scenario, selection)
    headline = _headline(
        status,
        findings,
        controls_state,
        completed,
        len(runs),
        len(runnable),
        _not_run_count(context),
        budget.exhausted,
    )
    case = CaseReport(
        case_id=scenario.id,
        pack="mcp",
        task=scenario.task,
        subject_kind="AGENT",
        divergence_status=status,
        validity=validity,
        execution_fidelity=FidelityRecord(found_on=scenario.fidelity.value),
        oracles=_oracle_records(scenario, None),
        stability=_counts_only_stability(baseline_outcomes, runnable, k),
        search=search_record,
        findings=findings,
        multiplicity=multiplicity,
        worlds=world_records,
        controls=ControlsRecord(
            status=controls_state,  # type: ignore[arg-type]
            detail=controls_detail,
        ),
        assumptions=[
            "A finding is evidence for review, not a verdict on the agent or the scenario.",
            "Roles come from the scenario's reference procedure on each world; a world outside the "
            "oracle's assumptions is reported as CANNOT_JUDGE.",
        ],
        headline=headline,
        elapsed_seconds=elapsed,
        extensions={
            "mcp": {
                "scenario_ref": scenario_ref,
                "agent_command": agent_command,
                "k": k,
                "runs": runs,
                "subject": json.loads(next(iter(subjects))) if len(subjects) == 1 else None,
                "worlds_total": len(results),
                "selection": selection,
                "isitright_version": __version__,
            }
        },
    )
    return AuditReport(
        pack="mcp",
        kind="scenario",
        cases=[case],
        totals=totals_of([case]),
        elapsed_seconds=elapsed,
        metadata={"seed": 0, "trial_count_per_world": k},
    )


def _summary(outcomes: list[RunOutcome]) -> Any:
    done = [o.outcome for o in outcomes if o.outcome is not None]
    if not done:
        return None
    if Outcome.NOT_MET in done:
        return "NOT_MET"
    if Outcome.CANNOT_JUDGE in done:
        return "CANNOT_JUDGE"
    return "MET"


def _path(world: World) -> list[MutationRecord]:
    return [
        MutationRecord(
            family=m.family,
            target=m.target,
            description=m.description,
            hints=m.hints,
            atoms=[list(a) for a in m.atoms],
        )
        for m in world.path
    ]


def _screening_record(context: ReportContext, world_id: str) -> ScreeningRecord | None:
    screened = context.screens.get(world_id)
    if screened is None:
        return None
    return ScreeningRecord(
        screening_class=screened.cls.value,
        basis=screened.basis,
        rank=context.ranks.get(world_id),
    )


def _not_run_count(context: ReportContext) -> int:
    return sum(1 for n in context.not_run if n.rank is not None or n.world.fixed is not None)


def _not_run_records(context: ReportContext) -> list[WorldRecord]:
    """The worlds that were not run, listed one by one (up to a limit), best-ranked first."""
    ordered = sorted(
        context.not_run, key=lambda n: (n.rank is None, n.rank if n.rank is not None else 0)
    )
    out: list[WorldRecord] = []
    for entry in ordered[:NOT_RUN_RECORDS]:
        rw = entry.world
        out.append(
            WorldRecord(
                id=rw.id,
                role=rw.role.value,
                description=rw.description,
                validity=rw.validity,
                oracle_outcome="CANNOT_JUDGE" if rw.reference.role is Role.UNJUDGEABLE else None,
                role_basis=rw.reference.basis,
                counts=count([]).model_dump(),
                mutation_path=_path(rw.world),
                screening=_screening_record(context, rw.id),
                run_status="NOT_RUN",
                not_run_reason=entry.reason,
            )
        )
    return out


def _reason_kind(reason: str) -> str:
    """The reason without the numbers that differ between worlds, for counting."""
    if reason.startswith("stratum stopped"):
        return "stratum stopped (stratum rule)"
    if reason.startswith("run stopped"):
        return "run stopped (no uncovered feature and no finding)"
    if reason.startswith("the oracle cannot judge"):
        return "the oracle cannot judge the world"
    return reason


def _selection(
    accounting: dict[str, Any], results: list[WorldResult], context: ReportContext
) -> dict[str, Any]:
    """Counts of what was generated, run and left unrun, for the reader and the report."""
    run_generated = [
        r for r in results if r.world.generated is not None and (r.outcomes or not r.world.runnable)
    ]
    unrun: dict[str, int] = {}
    for entry in context.not_run:
        key = _reason_kind(entry.reason)
        unrun[key] = unrun.get(key, 0) + 1
    generated = [rw.generated for rw in context.generated if rw.generated is not None]
    pool = eligible(generated)
    return {
        "generated": len(generated),
        "eligible": len(pool),
        "unjudgeable": sum(1 for w in generated if w.role is Role.UNJUDGEABLE),
        "unobservable": sum(
            1 for w in generated if w.role is not Role.UNJUDGEABLE and not w.observable
        ),
        "run": len(run_generated),
        "not_run": len(context.not_run),
        "not_run_by_reason": dict(sorted(unrun.items())),
        "not_run_listed": min(len(context.not_run), NOT_RUN_RECORDS),
        "ranking": context.ranking,
        "generation": accounting.get("generated_total"),
    }


def _mutation_records(path: Any) -> list[MutationRecord]:
    return [
        MutationRecord(
            family=m.family,
            target=m.target,
            description=m.description,
            hints=m.hints,
            atoms=[list(a) for a in m.atoms],
        )
        for m in path
    ]


def _minimization_record(result: NoisyMinimization | None, original: int) -> dict[str, Any]:
    """What the noisy minimization did, with its evidence. A path is replaced only when minimal."""
    if result is None:
        return {}
    return {
        "method": "delta debugging over the path's mutations, steps judged by a sequential test",
        "status": result.status.value,
        "minimal": result.minimal,
        "mutations_before": original,
        "mutations_after": len(result.path),
        "runs": result.runs,
        "kept": [m.description for m in result.path],
        "note": result.note,
        "confidence": result.confidence,
        "steps": [
            {"kept": list(s.kept), "decision": s.decision, "runs": s.runs, "failures": s.bad}
            for s in result.steps
        ],
    }


def _selection_note(selection: dict[str, Any]) -> str:
    reasons = "; ".join(f"{n} {why}" for why, n in selection["not_run_by_reason"].items())
    return (
        f"{selection['generated']} valid worlds generated, {selection['eligible']} judgeable and "
        f"observable, ranked by {selection['ranking']}; {selection['run']} run, "
        f"{selection['not_run']} not run"
        + (f" ({reasons})" if reasons else "")
        + ". Worlds not run are not evidence of correctness"
    )


def _counts_only_stability(
    baseline: list[RunOutcome] | None, runnable: list[WorldResult], k: int
) -> Any:
    """Case-level counts. A rate claim belongs to one world's paired runs (see each finding)."""
    if not baseline:
        return None
    world = [o for r in runnable for o in r.outcomes]
    flaky = 0 < sum(is_bad(b) for b in baseline) < len(baseline)
    note = "counts over all worlds that ran; a rate claim is made per world (see the findings)"
    if flaky:
        note = "the baseline itself is flaky, which weakens any finding. " + note
    return Stability(k=k, baseline=count(baseline), world=count(world), note=note)


def _hint_use(scenario: McpScenario, context: ReportContext) -> list[HintUse]:
    """Which hints led to which generated worlds (provenance shown, `proposed` marked)."""
    out = []
    for hint in scenario.hints:
        ids = [
            rw.id
            for rw in context.generated
            if rw.generated is not None
            and any(hint.name in m.hints for m in rw.generated.world.path)
        ]
        out.append(
            HintUse(
                name=hint.name,
                kind=hint.kind,
                provenance=hint.provenance.value,
                worlds=ids[:HINT_WORLDS_LISTED],
                world_count=len(ids),
            )
        )
    return out


def _search_record(
    accounting: dict[str, Any],
    budget: Budget,
    runs: int,
    context: ReportContext,
    scenario: McpScenario | None,
    selection: dict[str, Any],
) -> SearchRecord:
    screening = None
    if context.screens:
        counts: dict[str, int] = {c.value: 0 for c in ScreeningClass}
        for s in context.screens.values():
            counts[s.cls.value] += 1
        screening = ScreeningSummary(
            ranking=context.ranking,
            baseline_trace=context.trace_dir,
            counts=counts,
            note=(
                "screening replays the baseline trace on each world and runs the oracle, with no "
                "agent; it orders the runs and never removes a world from the report"
            ),
        )
    stopping = (
        context.stop.to_record(budget.exhausted)
        if context.stop is not None and context.stop.universe
        else None
    )
    extra: dict[str, Any] = {
        "screening": screening,
        "stopping": stopping,
        "hint_use": _hint_use(scenario, context) if scenario is not None else [],
    }
    if accounting:
        record = {k: v for k, v in accounting.items() if k not in ("selection", "generated_total")}
        if context.generated:
            record["notes"] = [*record.get("notes", []), _selection_note(selection)]
        record["budget"] = {**record.get("budget", {}), "runs": budget.to_json()}
        return SearchRecord(**record, **extra)
    return SearchRecord(
        seed=0,
        attempts=0,
        valid_candidates=0,
        executed=runs,
        budget={"runs": budget.to_json()},
        notes=["hand-written worlds only: no generation"],
    )


def _finding_headline(
    violated: list[str], reached_unmet: bool, affected: int, evaluated: int, world: str
) -> str:
    what = (
        f"Invariant '{safe_name(violated[0], 'invariant name')}' violated"
        if violated
        else "Expected behavior not reached"
    )
    return (
        f"{what} in {affected} of {evaluated} runs on world {safe_name(world, 'world id')} "
        "(attribution not assessed)"
    )


def _headline(
    status: DivergenceStatus,
    findings: list[Finding],
    controls: str,
    completed: int,
    runs: int,
    worlds: int,
    not_run: int = 0,
    stopped_by: str | None = None,
) -> str:
    if status is DivergenceStatus.UNSUPPORTED:
        return "Unsupported: no world in the scenario is valid"
    if status is DivergenceStatus.INCONCLUSIVE:
        if completed == 0:
            return "Inconclusive: the agent command produced no completed run"
        unrun = f"; {not_run} eligible worlds were not run" if not_run else ""
        if stopped_by:
            unrun += f" (the {stopped_by} budget ended the run)"
        return (
            "Inconclusive: no mutated world produced a judged run "
            f"(the baseline runs do not count; {worlds} mutated worlds were run){unrun}"
        )
    if findings:
        observed = [f for f in findings if f.evidence_grade is EvidenceGrade.OBSERVED_FAILURE]
        strong = [f for f in findings if f.evidence_grade is not EvidenceGrade.OBSERVED_FAILURE]
        top = max(
            strong or observed,
            key=lambda f: (
                any(o.kind == "INVARIANT" for o in f.oracles),
                f.divergence["runs_affected"],
            ),
        )
        text = safe_detail(top.headline)
        if strong:
            text = f"Rate increase decided: {text}"
            if observed:
                text += (
                    f"; {len(observed)} more world(s) with observed disagreements, no rate decided"
                )
            return text
        more = (
            f"; {len(observed) - 1} more world(s) with observed disagreements"
            if observed[1:]
            else ""
        )
        return f"Observed disagreement, no paired test decided a higher rate: {text}{more}"
    tail = {
        "DISCRIMINATING": "; control worlds behaved as expected",
        "NOT_APPLICABLE": "; no control world completed, so this is weak evidence",
        "NOT_DISCRIMINATING": "",
    }[controls]
    unrun = f"; {not_run} eligible worlds were not run" if not_run else ""
    if stopped_by:
        unrun += f" (the {stopped_by} budget ended the run)"
    return (
        f"No invariant violation or expectation mismatch in {runs} runs across {worlds} worlds"
        f"{unrun}{tail}"
    )


def write_report(report: AuditReport, output_dir: Path) -> None:
    """Write ``report.json`` (schema 0.5) and ``report.md`` (a human summary)."""
    for case in report.cases:
        for finding in case.findings:
            finding.replay.command = (
                f"isitright agents replay --report {replay_placeholder(output_dir, 'report.json')} "
                "--findings-only --trust-code"
            )
    (output_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    case = report.cases[0]
    mcp = case.extensions["mcp"]
    lines = [
        f"# {case.case_id}",
        "",
        f"**{case.headline}**",
        "",
        f"Divergence: {case.divergence_status.value}. "
        f"Validity: {', '.join(case.validity.tiers) or case.validity.status}. "
        f"Attribution: {case.attribution_status.value}. "
        f"Fidelity: {case.execution_fidelity.found_on}.",
    ]
    subject = mcp.get("subject")
    if subject:
        harness = (
            f"{subject['harness_name']} {subject['harness_version']}"
            if subject.get("harness_name")
            else "n/a"
        )
        lines.append(
            f"Stack under test: {subject['provider']} {subject['model']}; harness {harness}."
        )
    if case.controls:
        lines.append(f"Controls: {case.controls.status}. {case.controls.detail}")
    if case.stability and case.stability.baseline:
        base = case.stability.baseline
        lines.append(
            f"Baseline: {base.met} of {base.n} runs reached the expected behavior. "
            f"{case.stability.note}"
        )
    for note in case.search.notes:
        if "ranked by" in note:
            lines.append(f"Worlds: {note}.")
    stopping = case.search.stopping
    if stopping is not None:
        if stopping.run_stop_reason:
            lines.append(f"Run stopped: {stopping.run_stop_reason}.")
        lines += [
            f"- {s.family} / {s.target} / {s.role}: {s.summary}"
            for s in stopping.strata
            if s.stopped
        ]
    lines += [
        "",
        "| World | Role | Screening | Validity | Oracle | Runs | Violating runs | Not met |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for w in case.worlds[:200]:
        screened = w.screening.screening_class if w.screening else "-"
        oracle_text = "NOT RUN" if w.run_status == "NOT_RUN" else (w.oracle_outcome or "n/a")
        lines.append(
            f"| {w.id} | {w.role} | {screened} | "
            f"{', '.join(w.validity.tiers) or w.validity.status}"
            f"{' (unobservable)' if w.validity.unobservable else ''} | {oracle_text} "
            f"| {w.counts.get('n', 0)} | {w.counts.get('violated', 0)} "
            f"| {w.counts.get('not_met', 0)} |"
        )
    if len(case.worlds) > 200:
        lines.append(f"| ... {len(case.worlds) - 200} more worlds in report.json | | | | | | | |")
    if case.findings:
        lines += ["", "## Findings", ""]
        lines += [
            f"- {f.world_id} ({f.evidence_grade.value if f.evidence_grade else 'ungraded'}): "
            f"{f.headline}. Example: {f.divergence['example_run_dir']}."
            + (
                f" Test: {f.stability.sequential.decision.value} after "
                f"{f.stability.sequential.pairs} pairs."
                if f.stability and f.stability.sequential
                else ""
            )
            for f in case.findings
        ]
    lines += describe_graded_findings(case)
    lines += [
        "",
        "A finding is evidence for review, not a verdict on the agent or the scenario.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def export_eval_cases(
    scenario_ref: str, report: AuditReport, output_dir: Path, *, include_observed: bool = False
) -> list[EvalCase]:
    """Each finding as a new eval case: the world, the task, the recorded trace and the verdict.

    A finding graded ``OBSERVED_FAILURE`` is left out unless ``include_observed``: no paired test
    decided that its world raises the failure rate, so it is not yet a case to hold an agent to.
    """
    case = report.cases[0]
    cases: list[EvalCase] = []
    for finding in case.findings:
        if finding.evidence_grade is EvidenceGrade.OBSERVED_FAILURE and not include_observed:
            continue
        run_dir = contained_path(
            output_dir, str(finding.divergence["example_run_dir"]), what="run directory"
        )
        world = json.loads((run_dir / "world.json").read_text(encoding="utf-8"))
        run = next(
            r
            for r in case.extensions["mcp"]["runs"]
            if r["run_dir"] == finding.divergence["example_run_dir"]
        )
        cases.append(
            EvalCase(
                pack="mcp",
                case_id=f"{case.case_id}-{finding.world_id}",
                source_finding=finding.finding_id,
                payload={
                    "scenario_ref": scenario_ref,
                    "fixed_id": run.get("fixed_id"),
                    "task": case.task,
                    "world": world,
                    # a run that called no tool left no trace file: an empty trace, as when it ran
                    "trace": list(read_trace(run_dir / "trace.jsonl")),
                },
                expectation={
                    "disagreement": {
                        "violations": [v["invariant"] for v in run["violations"]],
                        "outcome": run["outcome"],
                    },
                    "world_sha256": sha256_text(json.dumps(world, sort_keys=True)),
                },
            )
        )
    return cases
