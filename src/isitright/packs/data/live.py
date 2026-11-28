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
from isitright.core.replay import ReplayArtifact
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.selection import (
    Ranking,
    Screened,
    ScreeningClass,
    StoppingRules,
    StopState,
    rank_worlds,
)
from isitright.core.sequential import PairedSprt, SprtConfig
from isitright.core.shown import built_from, world_json_fingerprint
from isitright.core.stochastic import (
    Budget,
    EvidenceGrade,
    RunOutcome,
    SubjectRunner,
    grade_of,
    is_bad,
    is_judged,
    multiplicity_of,
    observation_of,
    stability_sequential,
)
from isitright.core.subjects import Cost, SubjectKind
from isitright.core.world import diff_states
from isitright.packs.data.adapters import AgentRun, DataAgent
from isitright.packs.data.audit import DataAudit, _path, validity_record
from isitright.packs.data.comparison import undefined_answer
from isitright.packs.data.hints import harvest_program_hints
from isitright.packs.data.mapping import write_state
from isitright.packs.data.programs import RecordedProgram


@dataclass
class LiveConfig:
    baseline_runs: int = 3
    max_trials: int = 20
    attempts: int = 300
    seed: int = 0
    ranking: Ranking = "diverse"
    stratum_patience: int | None = 10
    run_patience: int | None = 30
    run_patience_share: float | None = 0.10
    max_worlds: int | None = 40
    verify_minimized_runs: int = 3
    sprt: SprtConfig | None = None
    allow_failing_baseline: bool = False
    """Audit although a baseline run did not meet the expectation (it is reported either way)."""


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


class _AgentSubject:
    """The agent as `SubjectRunner` runs it: on a world's state, in a scratch directory."""

    def __init__(self, audit: DataAudit, agent: DataAgent) -> None:
        self.audit = audit
        self.agent = agent

    def execute(self, target: WorldRuns, seed: int, /) -> AgentRun:
        with tempfile.TemporaryDirectory(prefix="isitright-live-") as scratch:
            write_state(target.world.world.state, self.audit.prepared.spec.schema, Path(scratch))
            return self.agent.solve(self.audit.task.question, Path(scratch))


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

    runner = _runner(audit, agent, budget, config, progress)
    comparison = WorldRuns(base.world)
    """Fresh baseline runs made for the pairs; `base` keeps the runs made before the search."""
    runner.run_repeated(base, config.baseline_runs, "baseline")
    _check_baseline(base, config)

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
        target = WorldRuns(w)
        results.append(target)
        staged = runner.run_staged(target, comparison, sprt_config, sprt_config.min_pairs)
        target.sprt = staged.test
        target.baselines = staged.baseline_outcomes
        stop.record(w, any(is_bad(o) for o in target.outcomes))
    verification = _verify_minimized(audit, runner, base, frozen_world, config)
    return _report(
        audit,
        agent,
        program,
        config,
        budget,
        base,
        comparison,
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


def _check_baseline(base: WorldRuns, config: LiveConfig) -> None:
    """Stop unless every baseline run met the expectation: a world is only a world of interest
    against a baseline that gets the task right."""
    if config.allow_failing_baseline:
        return
    met = sum(o.outcome is Outcome.MET and not o.error for o in base.outcomes)
    if base.outcomes and met == len(base.outcomes):
        return
    detail = (
        f"{met} of {len(base.outcomes)} baseline runs met the expectation"
        if base.outcomes
        else "no baseline run was made (the budget allowed none)"
    )
    raise LiveInputError(
        f"the baseline does not meet the expectation in every run: {detail}. A finding on a "
        "mutated world means little when the original world is already wrong. Fix the agent or "
        "the task, or pass --allow-failing-baseline to audit anyway."
    )


def _verification_text(record: dict[str, Any]) -> str:
    """What the separate run on the minimized world showed, in the three outcomes it can have."""
    if record["status"] == "OBSERVED_FAILURE":
        return f"the answer differed in {record['failures']} of {record['judged']} judged runs"
    if record["status"] == "NOT_REPRODUCED":
        return f"the answer did not differ in {record['judged']} judged runs"
    why = (
        f"the {record['stopped_by']} budget was spent first"
        if record["runs"] == 0 and record["stopped_by"]
        else f"{record['errors']} of {record['runs']} runs ended in an error"
        if record["runs"]
        else "it was not run"
    )
    return f"no run was judged ({why}): the disagreement is neither reproduced nor ruled out"


def _marker(outcome: RunOutcome) -> str:
    if outcome.error:
        return "E"
    return {Outcome.MET: ".", Outcome.NOT_MET: "N", Outcome.CANNOT_JUDGE: "?"}.get(
        outcome.outcome or Outcome.CANNOT_JUDGE, "?"
    )


def _verify_minimized(
    audit: DataAudit,
    runner: SubjectRunner[WorldRuns, AgentRun],
    base: WorldRuns,
    world: World | None,
    config: LiveConfig,
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
    runner.run_repeated(target, config.verify_minimized_runs, "confirm")
    return target


def _runner(
    audit: DataAudit,
    agent: DataAgent,
    budget: Budget,
    config: LiveConfig,
    progress: Callable[[str, str], None] | None,
) -> SubjectRunner[WorldRuns, AgentRun]:
    def judge(target: WorldRuns, run: AgentRun, tag: str) -> RunOutcome:
        _check_cost_reported(budget, run)
        outcome = _outcome(audit, target.world.gold_answer, run)
        target.runs.append(run)
        target.outcomes.append(outcome)
        target.answers.append(run.answer)
        if progress is not None:
            progress(target.world.id, _marker(outcome))
        return outcome

    return SubjectRunner(_AgentSubject(audit, agent), judge, budget, seed=config.seed)


def _counts(outcomes: list[RunOutcome]) -> dict[str, int]:
    return {
        "n": len(outcomes),
        "met": sum(o.outcome is Outcome.MET and not o.error for o in outcomes),
        "not_met": sum(o.outcome is Outcome.NOT_MET for o in outcomes),
        "cannot_judge": sum(o.outcome is Outcome.CANNOT_JUDGE for o in outcomes),
        "errors": sum(o.error for o in outcomes),
    }


def _json_safe(value: Any) -> Any:
    """The value as JSON holds it (numpy numbers and the like become their text)."""
    import json

    return json.loads(json.dumps(value, default=str))


def _outcome_name(outcome: RunOutcome) -> str:
    if outcome.error:
        return "ERROR"
    return outcome.outcome.value if outcome.outcome is not None else "ERROR"


def run_records(target: WorldRuns) -> list[dict[str, Any]]:
    """What the agent did on the world, run by run: the answer, the code if it returned any, and
    how the answer compared with the reference."""
    records = []
    for number, (run, outcome) in enumerate(zip(target.runs, target.outcomes, strict=True), 1):
        records.append(
            {
                "run": number,
                "outcome": _outcome_name(outcome),
                "answer": _json_safe(run.answer),
                "code": run.code or None,
                "error": run.error,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
            }
        )
    return records


def live_artifact(
    audit: DataAudit,
    agent: DataAgent,
    finding_id: str,
    target: WorldRuns,
    frozen_finding_id: str | None = None,
) -> ReplayArtifact:
    """The recorded observation of a live finding: the world, the reference, the policy and the
    agent's runs. Replaying it checks the reference and the recorded comparison (and executes the
    code the agent returned, where it returned any). It does not run the agent again."""
    records = run_records(target)
    code_answers: list[Any] = []
    for record in records:
        if record["code"] is None:
            code_answers.append(None)
            continue
        result = audit.host.run(record["code"], target.world.world.state)
        code_answers.append(_json_safe(result.answer()[0]) if result.status == "ok" else None)
    return ReplayArtifact(
        pack="data",
        case_id=finding_id,
        world=target.world.world.to_json(),
        host={"fidelity": "NATIVE_ISOLATED", "mode": "live"},
        inputs={
            "task_id": audit.task.id,
            "question": audit.task.question,
            "gold_code": audit.task.gold,
            "files": {f.table: f.file for f in audit.task.files},
            "schema": audit.prepared.spec.schema.model_dump(mode="json"),
            "policy": audit.comparator.describe(),
            "agent": {"name": agent.name, "model": agent.model},
            "runs": records,
            "frozen_finding": frozen_finding_id,
            "agent_rerun": False,
        },
        expected={
            "gold_answer": _json_safe(target.world.gold_answer),
            "recorded_outcomes": [r["outcome"] for r in records],
            "code_answers": code_answers,
        },
    )


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
    comparison: WorldRuns,
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
        finding_id = f"{task.id}:live:{target.world.id}"
        audit.artifacts[finding_id] = live_artifact(audit, agent, finding_id, target)
        fingerprint = target.world.world.fingerprint()
        findings.append(
            Finding(
                finding_id=finding_id,
                world_id=target.world.id,
                validity=validity_record(target.world.validity),
                oracles=[_oracle(NOT_MET)],
                stability=stability,
                evidence_grade=grade_of(target.sprt),
                observation=observation_of(target.outcomes, target.baselines),
                world_diff=diff_states(p.base, target.world.world.state),
                mutation_path=_path(target.world.world),
                divergence={
                    "scope": "the agent's own runs on this world, recorded; the agent is not "
                    "rerun by replay or export",
                    "agent": {"name": agent.name, "model": agent.model},
                    "agent_answers": [str(a)[:200] for a in target.answers],
                    "agent_runs": run_records(target),
                    "gold_answer": target.world.gold_answer,
                    "data_files": audit.data_files(target.world.world.state),
                    "gold_program": audit.task.gold,
                },
                fidelity=FidelityRecord(found_on="NATIVE_ISOLATED", verified_on="LIVE_AGENT"),
                mode="live_agent",
                live=_live_record(target, base),
                minimization={},
                world_fingerprint=fingerprint,
                built_from={
                    **built_from(fingerprint, "validity", "world_diff", "divergence", "counts"),
                    "replay": world_json_fingerprint(audit.artifacts[finding_id].world),
                },
                headline=(
                    f"The agent's answer differs from the reference in "
                    f"{sum(is_bad(o) for o in target.outcomes)} of {len(target.outcomes)} runs "
                    f"on a {target.world.id} world"
                ),
            )
        )
    generated_findings = list(findings)
    verification_record: dict[str, Any] | None = None
    if verification is not None:
        world_records.append(record(verification))
        verified_bad = sum(is_bad(o) for o in verification.outcomes)
        verified_finding: str | None = None
        if verified_bad:
            verified_finding = f"{task.id}:live:minimized"
            frozen_id = frozen_finding.finding_id if frozen_finding else None
            audit.artifacts[verified_finding] = live_artifact(
                audit, agent, verified_finding, verification, frozen_id
            )
            verified_fingerprint = verification.world.world.fingerprint()
            findings.append(
                Finding(
                    finding_id=verified_finding,
                    world_id="minimized",
                    validity=validity_record(verification.world.validity),
                    oracles=[_oracle(NOT_MET)],
                    evidence_grade=EvidenceGrade.OBSERVED_FAILURE,
                    observation=observation_of(verification.outcomes),
                    world_diff=diff_states(p.base, verification.world.world.state),
                    mutation_path=_path(verification.world.world),
                    divergence={
                        "scope": "the agent's own runs on the minimized frozen counterexample: a "
                        "separate verification, not one of the generated worlds of the search; "
                        "recorded, the agent is not rerun by replay or export",
                        "search_scope": "minimized_verification",
                        "agent": {"name": agent.name, "model": agent.model},
                        "agent_answers": [str(a)[:200] for a in verification.answers],
                        "agent_runs": run_records(verification),
                        "gold_answer": verification.world.gold_answer,
                        "data_files": audit.data_files(verification.world.world.state),
                        "gold_program": audit.task.gold,
                        "frozen_finding": frozen_id,
                    },
                    fidelity=FidelityRecord(found_on="NATIVE_ISOLATED", verified_on="LIVE_AGENT"),
                    mode="live_agent",
                    live=_live_record(verification, base),
                    minimization=dict(frozen_finding.minimization) if frozen_finding else {},
                    world_fingerprint=verified_fingerprint,
                    built_from={
                        **built_from(
                            verified_fingerprint, "validity", "world_diff", "divergence", "counts"
                        ),
                        "replay": world_json_fingerprint(audit.artifacts[verified_finding].world),
                    },
                    headline="The agent's answer differs from the reference on the minimized "
                    "world (separate verification, not a generated world)",
                )
            )
        verified = _counts(verification.outcomes)
        verified_judged = sum(is_judged(o) for o in verification.outcomes)
        # Three outcomes: a judged failure; judged runs and no failure; and nothing judged (all
        # runs errored, or none was made), which says nothing either way.
        verified_status = (
            "OBSERVED_FAILURE"
            if verified_bad
            else "NOT_REPRODUCED"
            if verified_judged
            else "INCONCLUSIVE"
        )
        verification_record = {
            "scope": "the minimized world of a frozen finding, run apart from the search; it is "
            "not one of the generated worlds and is not in `multiplicity`",
            "world": "minimized",
            "frozen_finding": frozen_finding.finding_id if frozen_finding else None,
            "runs": verified["n"],
            "failures": verified_bad,
            "requested_runs": config.verify_minimized_runs,
            "judged": verified_judged,
            "errors": verified["errors"],
            "stopped_by": budget.exhausted
            if verified["n"] < config.verify_minimized_runs
            else None,
            "status": verified_status,
            "finding": verified_finding,
            "grade": "OBSERVED_FAILURE" if verified_bad else None,
        }
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
    judged_search = sum(is_judged(o) for t in results for o in t.outcomes)
    status = (
        DivergenceStatus.COUNTEREXAMPLE_FOUND
        if any(f.evidence_grade is EvidenceGrade.RATE_INCREASE for f in findings)
        else DivergenceStatus.OBSERVED_FAILURE
        if findings
        else DivergenceStatus.INCONCLUSIVE
        if judged_search == 0
        else DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    )
    grades = {f.world_id: f.evidence_grade for f in findings}
    multiplicity = multiplicity_of(
        [(t.outcomes, grades.get(t.world.id)) for t in results],
        [*base.outcomes, *comparison.outcomes],
    )
    counts = {c.value: 0 for c in ScreeningClass}
    for s in screens.values():
        counts[s.cls.value] += 1
    ran = len(results)
    rate_worlds = sum(f.evidence_grade is EvidenceGrade.RATE_INCREASE for f in generated_findings)
    if generated_findings:
        summary = (
            f"the agent's answer differed from the reference in {len(generated_findings)} of "
            f"{ran} generated worlds run ({rate_worlds} with a rate increase decided by the "
            f"paired test, {len(generated_findings) - rate_worlds} observed only; "
            f"{len(not_run)} not run)"
        )
    elif judged_search == 0:
        summary = (
            f"no generated world produced a judged run ({ran} worlds run; the baseline runs do "
            f"not count; {len(not_run)} not run)"
        )
    else:
        summary = (
            f"no disagreement in the {ran} generated worlds the agent was run on "
            f"({len(not_run)} not run)"
        )
    if verification_record is not None:
        summary += "; separately, on the minimized frozen counterexample " + _verification_text(
            verification_record
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
        multiplicity=multiplicity,
        worlds=world_records,
        comparison_policy=audit.comparator.describe(),
        inputs={
            "task_id": task.id,
            "agent": agent.name,
            "model": agent.model,
            "frozen_program": program.program_id if program else None,
            "baseline_runs": base_counts,
            "paired_baseline_runs": _counts(comparison.outcomes),
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
                "verification": verification_record,
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
