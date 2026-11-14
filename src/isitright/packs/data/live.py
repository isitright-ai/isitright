"""Live mode: confirm frozen candidates with the agent itself.

The frozen replay of a recorded program ranks generated worlds (a world where the program already
disagrees with the reference is ``WRONG_IF_UNCHANGED``, one where it still agrees is
``RIGHT_IF_UNCHANGED``). The agent then runs on the ranked worlds under the 0.5 budgets, stopping
rules and sequential test, paired with its own baseline runs. A world the agent was not run on is
reported as not run. Results record where a candidate was found (the frozen program) and where it
was verified (the agent's own runs); the agent's code on each run is kept apart from the frozen
program, because a live agent may write different code once it sees different data.

This module never runs an agent's code itself: ``DataAgent.solve`` does, and the adapters run it in
a separate process.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from isitright.core.constraints import Validity
from isitright.core.evidence import (
    CaseReport,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    HintUse,
    LiveRecord,
    OracleRecord,
    ScreeningRecord,
    ScreeningSummary,
    SearchRecord,
    ValidityRecord,
    WorldRecord,
    headline_for,
)
from isitright.core.families import default_mutators
from isitright.core.hints import Hints
from isitright.core.mutations import Candidate, World
from isitright.core.oracles import Outcome, Role
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.selection import (
    Ranking,
    Screened,
    ScreeningClass,
    StoppingRules,
    StopState,
    rank_worlds,
)
from isitright.core.sequential import Decision, PairedSprt, SprtConfig
from isitright.core.stochastic import Budget, RunOutcome, is_bad, stability_sequential
from isitright.core.subjects import Cost, SubjectKind
from isitright.core.world import State, diff_states
from isitright.packs.data.adapters import AgentRun, DataAgent
from isitright.packs.data.audit import DataAudit, _path, validity_record
from isitright.packs.data.comparison import undefined_answer
from isitright.packs.data.hints import harvest_program_hints
from isitright.packs.data.mapping import write_state
from isitright.packs.data.programs import RecordedProgram


@dataclass
class LiveConfig:
    baseline_runs: int = 3
    max_trials: int = 10
    attempts: int = 300
    seed: int = 0
    ranking: Ranking = "diverse"
    stratum_patience: int | None = 10
    run_patience: int | None = 30
    run_patience_share: float | None = 0.10
    max_worlds: int | None = 40
    verify_minimized_runs: int = 3
    sprt: SprtConfig | None = None


@dataclass
class LiveWorld:
    """A generated world as the ranking sees it (`isitright.core.selection.Rankable`)."""

    id: str
    world: World
    validity: Validity
    screening: Screened
    frozen: Verdict | None
    gold_answer: Any
    observable: bool = True
    role: Role = Role.CONTROL


@dataclass
class WorldRuns:
    world: LiveWorld
    outcomes: list[RunOutcome] = field(default_factory=list)
    baselines: list[RunOutcome] = field(default_factory=list)
    runs: list[AgentRun] = field(default_factory=list)
    answers: list[Any] = field(default_factory=list)
    sprt: PairedSprt | None = None


def screening_class(program_verdict: Verdict, reason: str) -> Screened:
    if program_verdict is Verdict.AGREE:
        return Screened(
            ScreeningClass.RIGHT_IF_UNCHANGED,
            "the frozen program still agrees with the reference on this world",
        )
    if program_verdict is Verdict.DISAGREE:
        return Screened(
            ScreeningClass.WRONG_IF_UNCHANGED,
            "the frozen program disagrees with the reference on this world",
        )
    return Screened(ScreeningClass.UNSCREENABLE, f"the frozen replay could not decide ({reason})")


def generate_worlds(
    audit: DataAudit, program: RecordedProgram | None, hints: Hints, config: LiveConfig
) -> tuple[list[LiveWorld], SearchResult]:
    """Valid worlds within the attempt budget, each screened by the frozen program when there is
    one (the baseline excluded), in visiting order."""
    found: list[LiveWorld] = []
    p = audit.prepared

    def collect(candidate: Candidate, validity: Validity) -> Evaluation:
        world_id = "+".join(m.family for m in candidate.world.path) or "baseline"
        taken = {w.id for w in found}
        n, unique = 1, world_id
        while unique in taken:
            n += 1
            unique = f"{world_id}#{n}"
        if program is None:
            pair = None
            screened, verdict = Screened(ScreeningClass.UNSCREENABLE, "no recorded program"), None
            answer = audit.host.run(audit.task.gold, candidate.world.state).answer()[0]
        else:
            pair = audit.run_pair(program.code, candidate.world.state)
            verdict, reason, detail = audit.judge(pair)
            screened = screening_class(verdict, reason)
            answer = detail.get("gold_answer")
        # A reference answer that is NaN or infinite (a mean of nothing, a division by zero) gives
        # nothing to compare with, as in the frozen audit: the world is not judged, never scored.
        judged = (pair is None or pair.gold.status == "ok") and not undefined_answer(answer)
        found.append(
            LiveWorld(
                unique,
                candidate.world,
                validity,
                screened,
                verdict,
                answer,
                role=Role.CONTROL if judged else Role.UNJUDGEABLE,
            )
        )
        return Evaluation(Verdict.AGREE, validity)

    result = search(
        p.spec,
        World(p.base),
        hints,
        default_mutators(),
        collect,
        budget=Budget(attempts=config.attempts),
        seed=config.seed,
        depth=2,
        stop_on_first=False,
        compose_from="all",
        max_parents=300,
    )
    return found, result


class LiveInputError(ValueError):
    """The live audit cannot honor what was asked."""


def _check_cost_reported(budget: Budget, run: AgentRun) -> None:
    """A money budget cannot be enforced on an agent that reports no cost: refuse, do not guess."""
    if budget.money is not None and run.money is None and not run.error:
        raise LiveInputError(
            "a money budget needs the agent to report its cost; this agent reported none "
            "(pass usd_per_million_tokens to the adapter, or budget by runs)"
        )


def _outcome(audit: DataAudit, gold_answer: Any, run: AgentRun) -> RunOutcome:
    cost = Cost(run.input_tokens, run.output_tokens, run.money or 0.0)
    if run.error:
        return RunOutcome(None, error=True, cost=cost)
    comparison = audit.comparator.compare(gold_answer, run.answer)
    if comparison.inconclusive:
        return RunOutcome(Outcome.CANNOT_JUDGE, cost=cost)
    return RunOutcome(Outcome.MET if comparison.matches else Outcome.NOT_MET, cost=cost)


def _solve(audit: DataAudit, agent: DataAgent, state: State) -> AgentRun:
    with tempfile.TemporaryDirectory(prefix="isitright-live-") as scratch:
        write_state(state, audit.prepared.spec.schema, Path(scratch))
        return agent.solve(audit.task.question, Path(scratch))


def run_live(
    audit: DataAudit,
    agent: DataAgent,
    *,
    program: RecordedProgram | None = None,
    config: LiveConfig | None = None,
    budget: Budget | None = None,
    frozen_finding: Finding | None = None,
    frozen_world: World | None = None,
    only: list[str] | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> CaseReport:
    """Run ``agent`` on the baseline and then on the ranked worlds. ``program`` (the recording of
    the agent's baseline run) screens the worlds; without it every world is ``UNSCREENABLE`` and the
    order is by coverage. ``frozen_world`` is the minimized world of a frozen finding, which the
    agent is also run on as a verification of the minimized counterexample."""
    started = time.monotonic()
    config = config or LiveConfig()
    budget = budget or Budget()
    task, p = audit.task, audit.prepared
    hints = Hints(task.hints)
    if program is not None:
        hints = hints.merged(
            harvest_program_hints(program.code, p.spec.schema, task.files, question=task.question)
        )
    hints.validate(p.spec.schema)
    worlds, generation = generate_worlds(audit, program, hints, config)
    screens = {w.id: w.screening for w in worlds}
    base_gold = audit.host.run(task.gold, p.base).answer()[0]
    sprt_config = config.sprt or SprtConfig(
        min_pairs=config.baseline_runs, max_pairs=max(config.baseline_runs, config.max_trials)
    )

    base = WorldRuns(
        LiveWorld(
            "baseline",
            World(p.base),
            audit.prepared.spec.validate(p.base),
            Screened(ScreeningClass.UNSCREENABLE, "baseline"),
            None,
            base_gold,
        )
    )

    def trial(target: WorldRuns, number: int) -> RunOutcome:
        run = _solve(audit, agent, target.world.world.state)
        _check_cost_reported(budget, run)
        outcome = _outcome(audit, target.world.gold_answer, run)
        budget.record_run(outcome.cost)
        target.runs.append(run)
        target.outcomes.append(outcome)
        target.answers.append(run.answer)
        if progress is not None:
            progress(target.world.id, _marker(outcome))
        return outcome

    for number in range(config.baseline_runs):
        if not budget.can_run():
            break
        trial(base, number)

    ranked = rank_worlds(
        [w for w in worlds if w.role is not Role.UNJUDGEABLE],
        screens,
        mode=config.ranking,
        seed=config.seed,
    )
    ranks = {w.id: i + 1 for i, w in enumerate(ranked)}
    if only is not None:
        to_run = [w for w in worlds if w.id in set(only)]
    else:
        to_run = ranked if config.max_worlds is None else ranked[: config.max_worlds]
    rules = StoppingRules(config.stratum_patience, config.run_patience, config.run_patience_share)
    stop = StopState(rules, ranked)
    results: list[WorldRuns] = []
    not_run: dict[str, str] = {}
    for w in worlds:
        if w.role is Role.UNJUDGEABLE:
            not_run[w.id] = "the reference program cannot answer this world"
        elif w.id not in {x.id for x in to_run}:
            not_run[w.id] = (
                f"safety rail: --max-worlds {config.max_worlds} reached"
                if only is None
                else "not named in --only"
            )
    for w in to_run:
        reason = stop.skip_reason(w)
        if reason is None and not budget.can_run():
            reason = f"{budget.exhausted} budget exhausted"
            stop.record_budget(budget.exhausted)
        if reason is not None:
            not_run[w.id] = reason
            continue
        target = WorldRuns(w, baselines=list(base.outcomes), sprt=PairedSprt(sprt_config))
        results.append(target)
        for number in range(config.max_trials):
            if not budget.can_run():
                break
            outcome = trial(target, number)
            if not base.outcomes:
                break
            paired = base.outcomes[number % len(base.outcomes)]
            assert target.sprt is not None
            if target.sprt.add(is_bad(paired), is_bad(outcome)) is not Decision.CONTINUE:
                break
        stop.record(w, any(is_bad(o) for o in target.outcomes))
    verification = _verify_minimized(audit, agent, base, frozen_world, config, budget, progress)
    return _report(
        audit,
        agent,
        program,
        config,
        budget,
        base,
        results,
        not_run,
        screens,
        ranks,
        stop,
        generation,
        hints,
        started,
        frozen_finding,
        verification,
        len(worlds),
    )


def _marker(outcome: RunOutcome) -> str:
    if outcome.error:
        return "E"
    return {Outcome.MET: ".", Outcome.NOT_MET: "N", Outcome.CANNOT_JUDGE: "?"}.get(
        outcome.outcome or Outcome.CANNOT_JUDGE, "?"
    )


def _verify_minimized(
    audit: DataAudit,
    agent: DataAgent,
    base: WorldRuns,
    world: World | None,
    config: LiveConfig,
    budget: Budget,
    progress: Callable[[str, str], None] | None,
) -> WorldRuns | None:
    """Run the agent on the minimized world of a frozen finding."""
    if world is None or config.verify_minimized_runs < 1:
        return None
    gold = audit.host.run(audit.task.gold, world.state).answer()[0]
    target = WorldRuns(
        LiveWorld(
            "minimized",
            world,
            audit.prepared.spec.validate(world.state),
            Screened(ScreeningClass.WRONG_IF_UNCHANGED, "the minimized frozen counterexample"),
            Verdict.DISAGREE,
            gold,
        ),
        baselines=list(base.outcomes),
    )
    for _ in range(config.verify_minimized_runs):
        if not budget.can_run():
            break
        run = _solve(audit, agent, world.state)
        _check_cost_reported(budget, run)
        outcome = _outcome(audit, gold, run)
        budget.record_run(outcome.cost)
        target.runs.append(run)
        target.outcomes.append(outcome)
        target.answers.append(run.answer)
        if progress is not None:
            progress("minimized", _marker(outcome))
    return target


def _counts(outcomes: list[RunOutcome]) -> dict[str, int]:
    return {
        "n": len(outcomes),
        "met": sum(o.outcome is Outcome.MET and not o.error for o in outcomes),
        "not_met": sum(o.outcome is Outcome.NOT_MET for o in outcomes),
        "cannot_judge": sum(o.outcome is Outcome.CANNOT_JUDGE for o in outcomes),
        "errors": sum(o.error for o in outcomes),
    }


def _live_record(target: WorldRuns, base: WorldRuns) -> LiveRecord:
    base_codes = {r.code for r in base.runs}
    changed = sum(1 for r in target.runs if r.code and r.code not in base_codes)
    bad = sum(is_bad(o) for o in target.outcomes)
    return LiveRecord(
        status="CONFIRMED" if bad else "NOT_CONFIRMED",
        runs=len(target.runs),
        baseline_runs=len(base.runs),
        not_met=bad,
        agent_runs_only=True,
        program_changed_runs=changed,
        found_by_frozen_replay=target.world.frozen is Verdict.DISAGREE,
        note=(
            "the agent itself ran on this world; a count of observed disagreements with the "
            "reference, not a statement about failure rates unless a sequential test says so"
        ),
    )


def _report(
    audit: DataAudit,
    agent: DataAgent,
    program: RecordedProgram | None,
    config: LiveConfig,
    budget: Budget,
    base: WorldRuns,
    results: list[WorldRuns],
    not_run: dict[str, str],
    screens: dict[str, Screened],
    ranks: dict[str, int],
    stop: StopState,
    generation: SearchResult,
    hints: Hints,
    started: float,
    frozen_finding: Finding | None,
    verification: WorldRuns | None,
    generated: int,
) -> CaseReport:
    task, p = audit.task, audit.prepared
    findings: list[Finding] = []
    world_records: list[WorldRecord] = []

    def record(target: WorldRuns) -> WorldRecord:
        w = target.world
        counts = _counts(target.outcomes)
        return WorldRecord(
            id=w.id,
            role=w.role.value,
            description="; ".join(m.description for m in w.world.path) or "the unmutated baseline",
            validity=validity_record(w.validity),
            oracle_outcome=(
                "NOT_MET" if counts["not_met"] else ("MET" if counts["met"] else "CANNOT_JUDGE")
            ),
            counts=counts,
            mutation_path=_path(w.world),
            screening=ScreeningRecord(
                screening_class=w.screening.cls.value,
                basis=w.screening.basis,
                rank=ranks.get(w.id),
            ),
        )

    for target in results:
        world_records.append(record(target))
        if not any(is_bad(o) for o in target.outcomes):
            continue
        stability = (
            stability_sequential(
                target.baselines, target.outcomes, len(target.outcomes), target.sprt
            )
            if target.sprt is not None
            else None
        )
        findings.append(
            Finding(
                finding_id=f"{task.id}:live:{target.world.id}",
                world_id=target.world.id,
                validity=validity_record(target.world.validity),
                oracles=[_oracle(NOT_MET)],
                stability=stability,
                world_diff=diff_states(p.base, target.world.world.state),
                mutation_path=_path(target.world.world),
                divergence={
                    "scope": "the agent's own runs on this world",
                    "agent_answers": [str(a)[:200] for a in target.answers],
                    "gold_answer": target.world.gold_answer,
                },
                fidelity=FidelityRecord(found_on="NATIVE_ISOLATED", verified_on="LIVE_AGENT"),
                mode="live_agent",
                live=_live_record(target, base),
                minimization={},
                headline=(
                    f"The agent's answer differs from the reference in "
                    f"{sum(is_bad(o) for o in target.outcomes)} of {len(target.outcomes)} runs "
                    f"on a {target.world.id} world"
                ),
            )
        )
    if verification is not None:
        world_records.append(record(verification))
        if any(is_bad(o) for o in verification.outcomes):
            findings.append(
                Finding(
                    finding_id=f"{task.id}:live:minimized",
                    world_id="minimized",
                    validity=validity_record(verification.world.validity),
                    oracles=[_oracle(NOT_MET)],
                    world_diff=diff_states(p.base, verification.world.world.state),
                    mutation_path=_path(verification.world.world),
                    divergence={
                        "scope": "the agent's own runs on the minimized frozen counterexample",
                        "agent_answers": [str(a)[:200] for a in verification.answers],
                        "gold_answer": verification.world.gold_answer,
                        "frozen_finding": frozen_finding.finding_id if frozen_finding else None,
                    },
                    fidelity=FidelityRecord(found_on="NATIVE_ISOLATED", verified_on="LIVE_AGENT"),
                    mode="live_agent",
                    live=_live_record(verification, base),
                    minimization=dict(frozen_finding.minimization) if frozen_finding else {},
                    headline="The agent's answer differs from the reference on the minimized world",
                )
            )
    for world_id, reason in not_run.items():
        screened = screens.get(world_id)
        world_records.append(
            WorldRecord(
                id=world_id,
                role=Role.CONTROL.value,
                description="not run",
                validity=ValidityRecord(status="VALID"),
                run_status="NOT_RUN",
                not_run_reason=reason,
                screening=ScreeningRecord(
                    screening_class=screened.cls.value,
                    basis=screened.basis,
                    rank=ranks.get(world_id),
                )
                if screened
                else None,
            )
        )
    status = (
        DivergenceStatus.COUNTEREXAMPLE_FOUND
        if findings
        else DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    )
    counts = {c.value: 0 for c in ScreeningClass}
    for s in screens.values():
        counts[s.cls.value] += 1
    ran = len(results)
    summary = (
        f"the agent's answer differed from the reference in {len(findings)} of {ran} worlds run "
        f"({len(not_run)} not run)"
        if findings
        else f"no disagreement in the {ran} worlds the agent was run on ({len(not_run)} not run)"
    )
    account = generation.accounting()
    search_record = SearchRecord(
        **{**account, "budget": budget.to_json()},
        screening=ScreeningSummary(
            ranking=config.ranking,
            baseline_trace=program.program_id if program else None,
            counts=counts,
            note="screening replays the recorded program on each world: it ranks, not judges",
        ),
        stopping=stop.to_record(budget.exhausted),
        hint_use=[HintUse(name=h.name, kind=h.kind, provenance=h.provenance.value) for h in hints],
    )
    base_counts = _counts(base.outcomes)
    return CaseReport(
        case_id=f"{task.id}:live",
        pack="data",
        task=task.question or task.id,
        subject_kind=SubjectKind.AGENT.value,
        divergence_status=status,
        validity=findings[0].validity if findings else validity_record(p.spec.validate(p.base)),
        execution_fidelity=FidelityRecord(
            found_on="NATIVE_ISOLATED", verified_on="LIVE_AGENT" if findings else None
        ),
        oracles=[_oracle("NOT_MET" if findings else "MET")],
        search=search_record,
        findings=findings,
        worlds=world_records,
        comparison_policy=audit.comparator.describe(),
        inputs={
            "task_id": task.id,
            "agent": agent.name,
            "model": agent.model,
            "frozen_program": program.program_id if program else None,
            "baseline_runs": base_counts,
            "generated_worlds": generated,
        },
        assumptions=[
            "The agent's own runs are the evidence; the frozen program only ranked the worlds.",
            "A world the agent was not run on is reported as not run, never as passing.",
        ],
        headline=headline_for(status, summary),
        elapsed_seconds=time.monotonic() - started,
        extensions={
            "data": {
                "mode": "live",
                "baseline_codes": sorted({r.code for r in base.runs})[:3],
                "budget": budget.to_json(),
            }
        },
    )


NOT_MET: Literal["NOT_MET"] = "NOT_MET"


def _oracle(outcome: Literal["MET", "NOT_MET", "CANNOT_JUDGE"]) -> OracleRecord:
    return OracleRecord(
        name="gold program",
        kind="REFERENCE_PROGRAM",
        outcome=outcome,
        description="a reference program run on the same world with the same host",
        limits=["the gold program is an implementation written for this task; it can be wrong"],
    )
