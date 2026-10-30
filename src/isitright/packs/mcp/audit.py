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
    FidelityRecord,
    Finding,
    MutationRecord,
    OracleRecord,
    SearchRecord,
    ValidityRecord,
    WorldRecord,
    safe_detail,
    totals_of,
)
from isitright.core.mutations import World
from isitright.core.oracles import Outcome, Role, controls_status
from isitright.core.stochastic import (
    DEFAULT_K,
    Budget,
    RunOutcome,
    count,
    run_repeated,
    stability,
)
from isitright.core.world import diff_states, sha256_text
from isitright.packs.mcp.generate import GeneratedWorld, generate_worlds, select_worlds
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    FixedWorld,
    Interference,
    McpScenario,
    ScenarioError,
    absolute_reference,
    load_scenario,
)
from isitright.packs.mcp.oracle import EvaluationError, Reference, judge_run, reference_outcome
from isitright.packs.mcp.runner import (
    AgentRun,
    AgentsInputError,
    collect,
    harness_identity,
    run_agent,
    split_command,
    write_mcp_config,
)
from isitright.packs.mcp.serve import world_of

WorldSource = Literal["generated", "fixed", "all"]

__all__ = ["AgentsInputError", "RunWorld", "prepare_worlds", "run_scenario", "write_report"]

DEFAULT_MAX_WORLDS = 50
"""A safety rail on generated worlds, not a recommendation: set a money, run or time budget."""


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
    max_worlds: int | None,
    only: list[str] | None = None,
) -> tuple[list[RunWorld], dict[str, Any]]:
    """The baseline, then hand-written and/or generated worlds, each with its reference."""
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
        generated, result = generate_worlds(scenario, attempts=attempts, seed=seed)
        accounting = result.accounting()
        if only is None:
            generated, selection = select_worlds(generated, max_worlds)
            accounting["selection"] = selection
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


def _record_run(
    scenario: McpScenario,
    rw: RunWorld,
    trial: int,
    argv: list[str],
    scenario_ref: str,
    output_dir: Path,
    timeout: float,
    harness: tuple[str | None, str | None],
    result: WorldResult,
    require_cost: bool = False,
) -> RunOutcome:
    relative = f"runs/{rw.id}/{trial}"
    run_dir = output_dir / relative
    run_dir.mkdir(parents=True)
    (run_dir / "task.txt").write_text(scenario.task, encoding="utf-8")
    world_file = run_dir / "world.json"
    world_file.write_text(json.dumps(rw.world.to_json(), sort_keys=True), encoding="utf-8")
    mcp_config = write_mcp_config(
        run_dir,
        scenario_ref,
        world_file=None if rw.fixed is not None else world_file,
        fixed_id=rw.fixed.id if rw.fixed is not None else None,
    )
    started = time.monotonic()
    status, exit_code = run_agent(argv, run_dir, mcp_config, run_dir / "task.txt", rw.id, timeout)
    duration = time.monotonic() - started
    fallback = scenario.layout.to_service(rw.world.state)
    run = collect(run_dir, status, round(duration, 3), harness, fallback)
    if require_cost and status == "COMPLETED" and "money" not in run.extra:
        raise AgentsInputError(
            "a money budget needs the agent to report what each run cost, and this agent did not: "
            "write a transcript.json whose usage entries each have a 'cost' (see docs/agents.md), "
            "or bound the run with --max-runs or --max-seconds instead"
        )
    try:
        judgement = judge_run(scenario, rw.reference, run.before, run.after, run.trace)
    except EvaluationError as error:
        raise AgentsInputError(str(error)) from error
    calls = [e for e in run.trace if e["name"] != WORLD_CHANGE]
    writes = sum(1 for e in calls if (tool := scenario.tool(e["name"])) is not None and tool.writes)
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
            "trial": trial,
            "run_status": status,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "tool_calls": len(calls),
            "write_calls": writes,
            "violations": [{"invariant": n, "message": m} for n, m in judgement.violations],
            "outcome": judgement.outcome.value if completed else None,
            "run_dir": relative,
            "fixed_id": rw.fixed.id if rw.fixed is not None else None,
            "expectation_met": expectation_met,
            "cost": run.record.cost.money,
            **{k: v for k, v in run.extra.items() if k != "money"},
        }
    )
    if completed:
        result.violations.extend(judgement.violations)
        if (
            judgement.violations or judgement.outcome is Outcome.NOT_MET
        ) and result.example is None:
            result.example = run
            result.messages = judgement.messages
    return outcome


def run_scenario(
    *,
    scenario_ref: str,
    agent_command: str,
    output_dir: Path,
    worlds: WorldSource = "generated",
    k: int = DEFAULT_K,
    trials: int | None = None,
    timeout_seconds: float = 300.0,
    trust_code: bool = False,
    seed: int = 0,
    attempts: int = 20_000,
    max_worlds: int | None = DEFAULT_MAX_WORLDS,
    only: list[str] | None = None,
    budget: Budget | None = None,
) -> AuditReport:
    """Run ``agent_command`` on the baseline and on every valid world, ``k`` times each."""
    if not trust_code:
        raise AgentsInputError("running a scenario executes its code; pass trust_code=True")
    if importlib.util.find_spec("mcp") is None:
        raise AgentsInputError("the MCP SDK is not installed; run: pip install 'isitright[mcp]'")
    k = trials if trials is not None else k
    if k < 1 or timeout_seconds <= 0:
        raise AgentsInputError("trials must be at least 1 and the timeout positive")
    if output_dir.exists():
        raise AgentsInputError("output directory already exists; choose a new directory")
    reference_text = absolute_reference(scenario_ref)
    try:
        scenario = load_scenario(reference_text)
    except ScenarioError as error:
        raise AgentsInputError(str(error)) from error
    argv = split_command(agent_command)
    budget = budget or Budget()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True)
    harness = harness_identity(argv)
    started = time.monotonic()
    prepared, accounting = prepare_worlds(
        scenario, worlds, attempts=attempts, seed=seed, max_worlds=max_worlds, only=only
    )
    results: list[WorldResult] = []
    anything_to_audit = any(rw.runnable and not rw.baseline for rw in prepared)
    for rw in prepared:
        result = WorldResult(rw)
        results.append(result)
        if not rw.runnable or not anything_to_audit:
            continue

        def run_once(trial: int, rw: RunWorld = rw, result: WorldResult = result) -> RunOutcome:
            return _record_run(
                scenario,
                rw,
                trial + 1,
                argv,
                reference_text,
                output_dir,
                timeout_seconds,
                harness,
                result,
                budget.money is not None,
            )

        result.outcomes = run_repeated(run_once, k, budget)
    report = build_report(
        scenario,
        reference_text,
        agent_command,
        k,
        results,
        accounting,
        budget,
        round(time.monotonic() - started, 3),
    )
    write_report(report, output_dir)
    return report


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


def build_report(
    scenario: McpScenario,
    scenario_ref: str,
    agent_command: str,
    k: int,
    results: list[WorldResult],
    accounting: dict[str, Any],
    budget: Budget,
    elapsed: float,
) -> AuditReport:
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
                stability=stability(baseline_outcomes, outcomes, k),
                world_diff=diff_states(scenario.base, rw.world.state),
                mutation_path=_path(rw.world),
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
    completed = sum(1 for r in results for o in r.outcomes if not o.error)
    status = (
        DivergenceStatus.UNSUPPORTED
        if not runnable
        else DivergenceStatus.COUNTEREXAMPLE_FOUND
        if findings
        else DivergenceStatus.INCONCLUSIVE
        if completed == 0
        else DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    )
    pairs = [(r.world.role, [o.outcome for o in r.outcomes if o.outcome]) for r in results]
    controls_state, controls_detail = controls_status(
        [(role, [o for o in outs if o is not None]) for role, outs in pairs]
    )
    tiers_sets = [set(r.world.validity.tiers) for r in results if r.world.runnable]
    common = set.intersection(*tiers_sets) if tiers_sets else set()
    validity = (
        ValidityRecord(
            status="VALID",
            tiers=[t for t in ("STRUCTURAL", "DOMAIN_VALIDATED") if t in common],
        )
        if tiers_sets
        else ValidityRecord(status="INVALID")
    )
    runs = [run for r in results for run in r.runs]
    subjects = {
        json.dumps(run.get("subject"), sort_keys=True) for run in runs if run.get("subject")
    }
    search_record = _search_record(accounting, budget, len(runs))
    headline = _headline(status, findings, controls_state, len(runs), len(runnable))
    case = CaseReport(
        case_id=scenario.id,
        pack="mcp",
        task=scenario.task,
        subject_kind="AGENT",
        divergence_status=status,
        validity=validity,
        execution_fidelity=FidelityRecord(found_on=scenario.fidelity.value),
        oracles=_oracle_records(scenario, None),
        stability=stability(baseline_outcomes, [o for r in runnable for o in r.outcomes], k)
        if baseline_outcomes
        else None,
        search=search_record,
        findings=findings,
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
                "selection": accounting.get("selection"),
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


def _selection_note(selection: dict[str, Any]) -> str:
    return (
        f"{selection['generated']} valid worlds generated; {selection['selected']} selected for "
        f"the agent by feature coverage ({selection['features_covered']} of "
        f"{selection['features_total']} family/target/role features), {selection['not_selected']} "
        f"eligible not run, {selection['unjudgeable']} unjudgeable and "
        f"{selection['unobservable']} unobservable left out"
    )


def _search_record(accounting: dict[str, Any], budget: Budget, runs: int) -> SearchRecord:
    if accounting:
        record = {k: v for k, v in accounting.items() if k != "selection"}
        if "selection" in accounting:
            record["notes"] = [*record.get("notes", []), _selection_note(accounting["selection"])]
        record["budget"] = {**record.get("budget", {}), "runs": budget.to_json()}
        return SearchRecord(**record)
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
    what = f"Invariant '{violated[0]}' violated" if violated else "Expected behavior not reached"
    return f"{what} in {affected} of {evaluated} runs on world {world} (attribution not assessed)"


def _headline(
    status: DivergenceStatus,
    findings: list[Finding],
    controls: str,
    runs: int,
    worlds: int,
) -> str:
    if status is DivergenceStatus.UNSUPPORTED:
        return "Unsupported: no world in the scenario is valid"
    if status is DivergenceStatus.INCONCLUSIVE:
        return "Inconclusive: the agent command produced no completed run"
    if status is DivergenceStatus.COUNTEREXAMPLE_FOUND:
        top = max(
            findings,
            key=lambda f: (
                any(o.kind == "INVARIANT" for o in f.oracles),
                f.divergence["runs_affected"],
            ),
        )
        return safe_detail(top.headline)
    tail = {
        "DISCRIMINATING": "; control worlds behaved as expected",
        "NOT_APPLICABLE": "; no control world completed, so this is weak evidence",
        "NOT_DISCRIMINATING": "",
    }[controls]
    return (
        f"No invariant violation or expectation mismatch in {runs} runs across {worlds} worlds"
        f"{tail}"
    )


def write_report(report: AuditReport, output_dir: Path) -> None:
    """Write ``report.json`` (schema 0.4) and ``report.md`` (a human summary)."""
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
    lines += [
        "",
        "| World | Role | Validity | Oracle | Runs | Violating runs | Not met |",
        "|---|---|---|---|---|---|---|",
    ]
    for w in case.worlds[:200]:
        lines.append(
            f"| {w.id} | {w.role} | {', '.join(w.validity.tiers) or w.validity.status}"
            f"{' (unobservable)' if w.validity.unobservable else ''} | {w.oracle_outcome or 'n/a'} "
            f"| {w.counts.get('n', 0)} | {w.counts.get('violated', 0)} "
            f"| {w.counts.get('not_met', 0)} |"
        )
    if len(case.worlds) > 200:
        lines.append(f"| ... {len(case.worlds) - 200} more worlds in report.json | | | | | | |")
    if case.findings:
        lines += ["", "## Findings", ""]
        lines += [
            f"- {f.world_id}: {f.headline}. Example: {f.divergence['example_run_dir']}."
            for f in case.findings
        ]
    lines += [
        "",
        "A finding is evidence for review, not a verdict on the agent or the scenario.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def export_eval_cases(scenario_ref: str, report: AuditReport, output_dir: Path) -> list[EvalCase]:
    """Each finding as a new eval case: the world, the task, the recorded trace and the verdict."""
    case = report.cases[0]
    cases: list[EvalCase] = []
    for finding in case.findings:
        run_dir = output_dir / finding.divergence["example_run_dir"]
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
                    "trace": [
                        json.loads(line)
                        for line in (run_dir / "trace.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ],
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
