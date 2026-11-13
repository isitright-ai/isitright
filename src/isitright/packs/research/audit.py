"""The research audit: baseline, hints from the trace, search over mutated corpora, oracles,
minimization, replay and the report.

Two modes share the search. In *live* mode the subject (a stand-in, an in-process agent or an agent
command) runs again in each candidate world and the constructive and citation oracles judge its new
report. In *frozen* mode a recorded run is replayed: its queries are re-run on the world, its cited
documents re-read, and the report is not regenerated, so the audit can only say what the world does
to the recorded report and what the agent would now be shown; a finding there is scoped to the
recorded run, not to the agent.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from isitright.core.constraints import Validity, ValidityStatus
from isitright.core.evidence import (
    CaseReport,
    ControlsRecord,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    HintUse,
    MutationRecord,
    OracleRecord,
    ReplayRecord,
    ScreeningRecord,
    SearchRecord,
    ValidityRecord,
    WorldRecord,
    headline_for,
)
from isitright.core.hints import Hint, Hints
from isitright.core.minimize import minimize_path_noisy, minimize_world
from isitright.core.mutations import Candidate, Mutator, World
from isitright.core.oracles import Outcome, Role, controls_status
from isitright.core.replay import ReplayArtifact
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.sequential import Decision, PairedSprt, SprtConfig
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import (
    Budget,
    RunOutcome,
    is_bad,
    run_repeated,
    stability,
    stability_sequential,
)
from isitright.core.subjects import Cost, SubjectKind
from isitright.core.world import State, diff_states, sha256_text
from isitright.packs.research.agents import Agent, ResearchTask, ToolClient
from isitright.packs.research.documents import COLLECTION, documents_of, world_spec
from isitright.packs.research.hints import hints_from_run
from isitright.packs.research.mutators import all_mutators
from isitright.packs.research.oracle import Expect, judge
from isitright.packs.research.oracle import Verdict as Judged
from isitright.packs.research.replaying import export_case
from isitright.packs.research.retrieval import (
    RETRIEVER_STATEMENTS,
    FrozenStats,
    ToolHost,
    build_index,
    terms_of,
    tokenize,
)
from isitright.packs.research.runs import (
    RecordedRun,
    SubjectLabel,
    check_citations,
    normalize,
    same_answer,
)

PACK = "research"
ORACLE_LIMITS = [
    "the expected behavior is computed from the declared fact span and the documents a mutation "
    "added; it is a reference procedure written for this pack, and it can be wrong or incomplete",
    "answers are compared after a declared normalization; free text is not judged",
    "support of a claim by its cited document (L2) is not judged: no model judge is run",
]
ASSUMPTIONS = [
    "Retrieval is a frozen BM25 whose statistics come from the original corpus; findings describe "
    "this retriever, not the one the agent would use in production.",
    "The corpus tools are simulated (SIMULATED); a stand-in or recorded subject is labeled "
    "as such.",
    "Generated worlds are validated against the declared metadata rules; domain validation means "
    "the rules supplied held, not that a planted document is plausible.",
    "Attribution stays UNDETERMINED; the classification under extensions.research is a proposal by "
    "the implementing assistant.",
]


class ResearchInputError(ValueError):
    """The corpus, task or subject cannot be audited; the message says why."""


@dataclass
class AuditConfig:
    seed: int = 0
    attempts: int = 500
    depth: int = 2
    runs: int | None = None
    """Runs per world (default 1 for a deterministic subject, 4 for a stochastic one)."""
    sequential: bool = True
    max_pairs: int = 16
    minimize: bool = True
    minimized_findings: int = 3
    minimization_max_attempts: int = 300
    max_findings: int = 50
    allow_failing_baseline: bool = False
    screen: bool = False
    seconds: float | None = None
    money: float | None = None
    max_runs: int | None = None
    mutators: Sequence[Mutator] | None = None
    declared_hints: Sequence[Hint] = ()
    k_search: int = 5
    retriever: str = "bm25"
    """``bm25`` (the 0.8 retriever), ``hashed-dense`` or ``hybrid`` (see `retrieval.py`)."""


Executor = Callable[[World, int], RecordedRun]


@dataclass
class Subject:
    label: SubjectLabel
    stochastic: bool
    execute: Executor
    kind: SubjectKind = SubjectKind.AGENT
    reports_cost: bool = False
    """Whether runs report money. A money budget is refused for a subject that does not."""


def validity_record(validity: Validity, unobservable: bool = False) -> ValidityRecord:
    return ValidityRecord(
        status=validity.status.value,
        tiers=[t.value for t in validity.tiers],
        problems=list(validity.problems),
        notes=list(validity.notes),
        unobservable=unobservable,
    )


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


def _derived_seed(base: int, label: str, trial: int) -> int:
    digest = hashlib.sha256(f"{base}:{label}:{trial}".encode()).hexdigest()
    return int(digest[:8], 16)


@dataclass
class WorldResult:
    world: World
    validity: Validity
    runs: list[RecordedRun] = field(default_factory=list)
    judged: list[Judged] = field(default_factory=list)
    outcomes: list[RunOutcome] = field(default_factory=list)
    sequential: PairedSprt | None = None
    role: Role = Role.TRAP
    role_basis: str = ""
    unobservable: bool = False
    observed_ids: list[str] = field(default_factory=list)
    screening: str | None = None
    screening_basis: str = ""
    not_run: str | None = None
    tie: bool = False


def in_process_executor(agent: Agent, task: ResearchTask, stats: FrozenStats) -> Executor:
    """Run an in-process agent on a world through a `ToolHost` (the corpus tools are simulated)."""

    def execute(world: World, seed: int) -> RecordedRun:
        host = ToolHost(
            build_index(stats, list(world.state.entities(COLLECTION))), world.response_edits
        )
        status = "COMPLETED"
        try:
            report = agent.run(ToolClient(host), task, seed)
        except Exception as error:  # a subject crash is a subject error, never a finding
            from isitright.packs.research.runs import Report

            report = Report(answer=None)
            status = "SUBJECT_ERROR"
            host.events.append(
                {
                    "index": len(host.events),
                    "name": "_agent_error",
                    "arguments": {},
                    "result": f"{type(error).__name__}: {error}",
                    "is_error": True,
                }
            )
        return RecordedRun(
            subject=agent.label,
            task_id=task.id,
            question=task.question,
            trace=list(host.events),
            report=report,
            status=status,  # type: ignore[arg-type]
        )

    return execute


def stand_in_subject(agent: Agent, task: ResearchTask, stats: FrozenStats) -> Subject:
    return Subject(agent.label, agent.stochastic, in_process_executor(agent, task, stats))


class ResearchAudit:
    def __init__(
        self,
        state: State,
        task: ResearchTask,
        config: AuditConfig | None = None,
        *,
        stats: FrozenStats | None = None,
    ) -> None:
        self.config = config or AuditConfig()
        self.task = task
        if task.cutoff and "cutoff" not in state.params:
            state = state.evolve(params={"cutoff": task.cutoff})
        self.state = state
        self.spec: WorldSpec = world_spec(task.id)
        self.base = World(state)
        validity = self.spec.validate(state)
        if validity.status is not ValidityStatus.VALID:
            raise ResearchInputError("the corpus is not valid: " + "; ".join(validity.problems[:3]))
        self.base_validity = validity
        # ``stats`` lets a caller whose state is a restricted world of a larger corpus (a
        # benchmark task) give the statistics of the whole corpus: ranks do not depend on the
        # restriction.
        self.stats = stats or FrozenStats.from_documents(
            state.entities(COLLECTION), self.config.retriever
        )
        self.artifacts: dict[str, ReplayArtifact] = {}
        self.exports: dict[str, Any] = {}
        self.baseline_runs: list[RecordedRun] = []
        self.cannot_judge_rows: list[dict[str, Any]] = []
        self._frozen_fidelity: dict[str, Any] = {}
        """Every run the constructive oracle could not judge, with its full answer: written
        beside the report as cannot-judge.jsonl, not inside it (answers can be long)."""

    # -- plumbing ----------------------------------------------------------------------------

    def host(self, world: World) -> ToolHost:
        return ToolHost(
            build_index(self.stats, list(world.state.entities(COLLECTION))), world.response_edits
        )

    def stand_in(self, agent: Agent) -> Subject:
        return stand_in_subject(agent, self.task, self.stats)

    def replay_queries(self, world: World, queries: list[dict[str, Any]]) -> list[list[str]]:
        index = build_index(self.stats, list(world.state.entities(COLLECTION)))
        host = ToolHost(index, world.response_edits)
        out = []
        for q in queries:
            text, error = host.try_call("search", {"query": q["query"], "k": q["k"]})
            out.append([] if error else [r["id"] for r in json.loads(text)["results"]])
        return out

    # -- live mode ---------------------------------------------------------------------------

    def check(self, subject: Subject) -> CaseReport:
        started = time.monotonic()
        config, task = self.config, self.task
        k = config.runs or (4 if subject.stochastic else 1)
        budget = Budget(
            attempts=config.attempts,
            runs=config.max_runs,
            seconds=config.seconds,
            money=config.money,
        )
        baseline_runs: list[RecordedRun] = []
        baseline_outcomes: list[RunOutcome] = []
        baseline_k = k if subject.stochastic else 1
        for trial in range(baseline_k):
            seed = _derived_seed(config.seed, "baseline", trial)
            run = subject.execute(self.base, seed)
            run.seed = seed
            budget.record_run(_cost_of(run))
            baseline_runs.append(run)
        baseline = baseline_runs[0]
        self.baseline_runs = baseline_runs
        if config.money is not None and "money" not in baseline.cost:
            raise ResearchInputError(
                "a money budget needs an agent that reports its cost: the baseline run reported "
                "none "
                "(write usage with a cost into transcript.json, or budget in runs and seconds)"
            )
        if baseline.status != "COMPLETED":
            return self._unsupported(
                subject, started, "the baseline run did not complete", baseline_runs
            )
        gate = self._baseline_gate(baseline)
        if gate and not config.allow_failing_baseline:
            return self._inconclusive_baseline(subject, started, gate, baseline_runs)
        hints = hints_from_run(baseline, task.answer_type, task.question, documents_of(self.state))
        if config.declared_hints:
            hints = hints.merged(config.declared_hints)
        fact = _fact_args(hints)
        if fact is None:
            note = (
                "no fact span: the baseline report cites no quote that holds its answer, so the "
                "text-editing families are skipped (remove, duplicate need one too)"
            )
        else:
            note = ""
        baseline_outcomes = [
            self._baseline_outcome(self.base, r, baseline, fact) for r in baseline_runs
        ]
        results: dict[str, WorldResult] = {}
        base_citations = check_citations(baseline.report, documents_of(self.state)).to_json()

        def evaluate(candidate: Candidate, validity: Validity) -> Evaluation:
            return self._evaluate_live(
                candidate, validity, subject, baseline, baseline_outcomes, fact, k, budget, results
            )

        mutators = list(config.mutators) if config.mutators is not None else all_mutators()
        result = search(
            self.spec,
            self.base,
            hints,
            mutators,
            evaluate,
            budget=budget,
            seed=config.seed,
            depth=config.depth,
            stop_on_first=False,
            include_base=True,
        )
        if note:
            result.notes.append(note)
        findings = self._findings(
            result, results, subject, baseline, baseline_outcomes, fact, k, hints
        )
        return self._report(
            subject,
            started,
            result,
            results,
            findings,
            baseline_runs,
            baseline_outcomes,
            base_citations,
            hints,
            budget,
            gate,
            mode="live",
        )

    def _baseline_gate(self, baseline: RecordedRun) -> str | None:
        """Why the baseline cannot be audited, or None. A baseline that does not match a stated gold
        answer is not a passing eval."""
        task = self.task
        report = baseline.report
        if report.abstained():
            return "the baseline report abstains: there is no answer to audit"
        if task.gold is not None:
            same = same_answer(report.answer, task.gold, task.answer_type)
            if same is None:
                return (
                    f"the baseline answer {report.answer!r} cannot be read as a {task.answer_type}"
                )
            if not same:
                return (
                    f"the baseline answer {report.answer!r} does not match the gold {task.gold!r} "
                    f"({task.gold_basis})"
                )
        return None

    def _baseline_outcome(
        self, world: World, run: RecordedRun, reference: RecordedRun, fact: dict[str, Any] | None
    ) -> RunOutcome:
        if run.status != "COMPLETED":
            return RunOutcome(None, error=True)
        verdict = judge(world, run, reference, fact, self.task.answer_type)
        return RunOutcome(verdict.outcome, violated=verdict.invariant.outcome is Outcome.NOT_MET)

    def _trial(
        self,
        subject: Subject,
        world: World,
        baseline: RecordedRun,
        fact: dict[str, Any] | None,
        result: WorldResult,
        label: str,
    ) -> Callable[[int], RunOutcome]:
        def run_trial(trial: int) -> RunOutcome:
            seed = _derived_seed(self.config.seed, label, trial)
            run = subject.execute(world, seed)
            run.seed = seed
            result.runs.append(run)
            if run.status != "COMPLETED":
                return RunOutcome(None, error=True)
            verdict = judge(world, run, baseline, fact, self.task.answer_type)
            result.judged.append(verdict)
            if label not in ("min", "confirm"):
                self._note_cannot_judge(world, run, verdict, trial)
            return RunOutcome(
                verdict.outcome,
                violated=verdict.invariant.outcome is Outcome.NOT_MET,
                cost=_cost_of(run),
            )

        return run_trial

    def _note_cannot_judge(
        self, world: World, run: RecordedRun, verdict: Judged, trial: int
    ) -> None:
        if verdict.constructive.outcome is not Outcome.CANNOT_JUDGE:
            return
        self.cannot_judge_rows.append(
            {
                "world": world.fingerprint(),
                "mutations": [m.description for m in world.path],
                "family": "+".join(m.family for m in world.path) or "baseline",
                "trial": trial,
                "seed": run.seed,
                "answer": run.report.answer,
                "reason": "; ".join(verdict.constructive.messages),
                "expectation": verdict.expectation.kind.value,
            }
        )

    def _evaluate_live(
        self,
        candidate: Candidate,
        validity: Validity,
        subject: Subject,
        baseline: RecordedRun,
        baseline_outcomes: list[RunOutcome],
        fact: dict[str, Any] | None,
        k: int,
        budget: Budget,
        results: dict[str, WorldResult],
    ) -> Evaluation:
        world = candidate.world
        wr = WorldResult(world, validity)
        results[world.fingerprint()] = wr
        if self.config.screen and fact is not None:
            screen, basis = self.screen(world, baseline, fact)
            wr.screening, wr.screening_basis = screen, basis
            if screen in ("RIGHT_IF_UNCHANGED",):
                wr.not_run = f"screened out: {basis}"
                return Evaluation(Verdict.REJECTED, validity, reason="screened_out")
        run_trial = self._trial(subject, world, baseline, fact, wr, world.fingerprint())
        if subject.stochastic and self.config.sequential and len(baseline_outcomes) > 1:
            self._paired(subject, world, baseline, baseline_outcomes, fact, wr, budget)
        else:
            wr.outcomes = run_repeated(run_trial, k, budget)
        if not wr.outcomes:
            return Evaluation(Verdict.INCONCLUSIVE, validity, reason="no run completed")
        if wr.judged:
            first = wr.judged[0]
            wr.role, wr.role_basis = first.expectation.role, first.expectation.basis
        self._observability(wr, baseline)
        wr.tie = self._tie(wr)
        if wr.unobservable:
            return Evaluation(
                Verdict.INCONCLUSIVE,
                validity,
                detail=wr,
                reason="unobservable_change",
            )
        if all(o.error for o in wr.outcomes):
            return Evaluation(Verdict.ERROR, validity, reason="every run ended in a subject error")
        if any(is_bad(o) for o in wr.outcomes):
            return Evaluation(Verdict.DISAGREE, validity, detail=wr)
        if all(o.outcome is Outcome.CANNOT_JUDGE or o.error for o in wr.outcomes):
            return Evaluation(Verdict.INCONCLUSIVE, validity, detail=wr, reason="cannot_judge")
        return Evaluation(Verdict.AGREE, validity, detail=wr)

    def _paired(
        self,
        subject: Subject,
        world: World,
        baseline: RecordedRun,
        baseline_outcomes: list[RunOutcome],
        fact: dict[str, Any] | None,
        wr: WorldResult,
        budget: Budget,
    ) -> None:
        test = PairedSprt(SprtConfig(max_pairs=self.config.max_pairs))
        wr.sequential = test
        run_trial = self._trial(subject, world, baseline, fact, wr, world.fingerprint())
        for pair in range(self.config.max_pairs):
            if not budget.can_run():
                break
            outcome = run_trial(pair)
            budget.record_run(outcome.cost)
            wr.outcomes.append(outcome)
            if outcome.error:
                continue
            base_bad = is_bad(baseline_outcomes[pair]) if pair < len(baseline_outcomes) else False
            if test.add(base_bad, is_bad(outcome)) is not Decision.CONTINUE:
                break

    def _observability(self, wr: WorldResult, baseline: RecordedRun) -> None:
        """A planted or changed document no query can retrieve is unobservable: a corpus or
        retrieval finding, not an agent finding. Queries are the ones the runs in this world made
        and the ones of the baseline (replayed on this world)."""
        docs = documents_of(wr.world.state)
        targets = [
            i for i, d in docs.items() if (d.get("provenance") or {}).get("kind") is not None
        ]
        seen: list[str] = []
        for run in wr.runs:
            seen.extend(run.seen())
        for ids in self.replay_queries(wr.world, baseline.queries()):
            seen.extend(ids)
        wr.observed_ids = sorted(set(seen))
        added = [t for t in targets if (docs[t]["provenance"]).get("kind") != "retract"]
        wr.unobservable = bool(added) and not any(t in set(seen) for t in added)

    def _tie(self, wr: WorldResult) -> bool:
        """Whether an added copy scored exactly like the document it was copied from for the
        baseline's first query (the rank between them is then decided by the id tie-break)."""
        docs = documents_of(wr.world.state)
        index = build_index(self.stats, list(wr.world.state.entities(COLLECTION)))
        scores = {h.id: h.score for h in index.rank(self.task.question, 50)}
        for doc_id, doc in docs.items():
            origin = (doc.get("provenance") or {}).get("derived_from")
            if (
                origin
                and doc_id in scores
                and origin in scores
                and scores[doc_id] == scores[origin]
            ):
                return True
        return False

    # -- screening -----------------------------------------------------------------------------

    def screen(self, world: World, baseline: RecordedRun, fact: dict[str, Any]) -> tuple[str, str]:
        """Replay the baseline's queries on ``world`` and say what the replay shows. Ranking input,
        never a verdict: it cannot know what the agent would do with what it is shown."""
        if world.response_edits:
            return (
                "UNSCREENABLE",
                "a response edit changes what the agent sees; only a run shows it",
            )
        docs = documents_of(world.state)
        expectation = judge(world, baseline, baseline, fact, self.task.answer_type)
        check = check_citations(baseline.report, docs)
        if check.l0_failures or check.l1_failures:
            return (
                "WRONG_IF_UNCHANGED",
                "the recorded report cites a document or quote the world lacks",
            )
        if expectation.expectation.kind is Expect.ABSTAIN_OR_FLAG:
            return "WRONG_IF_UNCHANGED", expectation.expectation.basis
        targets = expectation.expectation.targets
        lists = self.replay_queries(world, baseline.queries())
        exposed = [t for t in targets if any(t in ids for ids in lists)]
        if exposed and expectation.expectation.kind in (Expect.NEWER, Expect.KEEP_OR_FLAG):
            return "STALE", f"{exposed[0]} would appear in the results of a recorded query"
        if exposed:
            return (
                "UNSCREENABLE",
                f"{exposed[0]} would appear; only a run shows what the agent does",
            )
        return (
            "RIGHT_IF_UNCHANGED",
            "no document the world added or changed appears in the recorded queries",
        )

    # -- findings ------------------------------------------------------------------------------

    def _findings(
        self,
        result: SearchResult,
        results: dict[str, WorldResult],
        subject: Subject,
        baseline: RecordedRun,
        baseline_outcomes: list[RunOutcome],
        fact: dict[str, Any] | None,
        k: int,
        hints: Hints,
    ) -> list[Finding]:
        ordered = sorted(
            result.findings,
            key=lambda f: (-len(f.validity.tiers), len(f.candidate.world.path)),
        )[: self.config.max_findings]
        out: list[Finding] = []
        for number, found in enumerate(ordered, start=1):
            minimize = self.config.minimize and number <= self.config.minimized_findings
            out.append(
                self._finding(
                    number,
                    found.candidate.world,
                    found.validity,
                    results,
                    subject,
                    baseline,
                    baseline_outcomes,
                    fact,
                    minimize,
                )
            )
        return out

    def _finding(
        self,
        number: int,
        world: World,
        validity: Validity,
        results: dict[str, WorldResult],
        subject: Subject,
        baseline: RecordedRun,
        baseline_outcomes: list[RunOutcome],
        fact: dict[str, Any] | None,
        minimize: bool,
    ) -> Finding:
        case_id = f"{self.task.id}:{subject.label.name}"
        original = results[world.fingerprint()]
        kind = original.judged[0].expectation.kind if original.judged else None
        final, minimization = world, {"minimized": False}
        if minimize:
            final, minimization = self._minimize(world, subject, baseline, fact, kind)
        # Confirmation and the verdict shown are on the world that is shown.
        shown = WorldResult(final, self.spec.validate_world(final.state, world.path))
        trial = self._trial(subject, final, baseline, fact, shown, "confirm")
        k = max(1, len(original.runs))
        bad_runs = 0
        for t in range(k):
            bad_runs += is_bad(trial(t))
        verdict = shown.judged[0] if shown.judged else None
        worst = next((j for j in shown.judged if j.outcome is Outcome.NOT_MET), verdict)
        run = shown.runs[shown.judged.index(worst)] if worst in shown.judged else shown.runs[0]
        reproduces = bad_runs > 0
        self._observability(shown, baseline)
        self.artifacts[f"{case_id}:{number}"] = self._artifact(
            case_id, number, final, subject, baseline, run, worst, fact
        )
        docs_before = [
            {"id": i, "title": d.get("title"), "date": d.get("date"), "text": d["text"]}
            for i, d in sorted(documents_of(self.state).items())
            if i in documents_of(final.state) or i in _cited(baseline)
        ]
        docs_after = [
            {
                "id": i,
                "title": d.get("title"),
                "date": d.get("date"),
                "source": d.get("source"),
                "provenance": d.get("provenance"),
                "text": d["text"],
            }
            for i, d in sorted(documents_of(final.state).items())
        ]
        self.exports[f"{case_id}:{number}"] = export_case(self.artifacts[f"{case_id}:{number}"])
        gold_note = (
            f"gold {self.task.gold!r}: {self.task.gold_basis}"
            if self.task.gold is not None
            else "no gold answer was given; the baseline answer is the reference"
        )
        return Finding(
            finding_id=f"{case_id}:{number}",
            world_id=final.fingerprint(),
            validity=validity_record(shown.validity, shown.unobservable),
            oracles=_oracle_records(worst),
            stability=stability_sequential(
                baseline_outcomes, original.outcomes, k, original.sequential
            )
            if original.sequential is not None
            and original.sequential.decision is not Decision.CONTINUE
            else stability(baseline_outcomes, original.outcomes, k)
            if subject.stochastic
            else None,
            world_diff=diff_states(self.state, final.state),
            mutation_path=_path(world),
            divergence={
                "scope": "this subject on this world",
                "subject": subject.label.model_dump(mode="json"),
                "reproduces_on_shown_world": reproduces,
                "question": self.task.question,
                "baseline_report": baseline.report.model_dump(mode="json"),
                "world_report": run.report.model_dump(mode="json"),
                "expectation": worst.expectation.to_json() if worst else None,
                "behavior": worst.behavior.value if worst else None,
                "answer_changed": worst.answer_changed if worst else None,
                "citations": worst.citations if worst else None,
                "flag_basis": worst.flag_basis if worst else None,
                "oracle_messages": (
                    worst.constructive.messages + worst.invariant.messages if worst else []
                ),
                "documents_original": docs_before,
                "documents_in_world": docs_after,
                "reference_trust": gold_note,
                "tie_break_decided_rank": shown.tie,
                "found_on_world": world.fingerprint(),
                "shown_world": final.fingerprint(),
                "shown_world_is_minimized": bool(minimization.get("minimized")),
            },
            fidelity=FidelityRecord(found_on="SIMULATED", engine="frozen BM25 (isitright)"),
            replay=ReplayRecord(artifact=f"{number}.replay.json"),
            export=f"{number}.eval-case.json",
            minimization=minimization,
            mode="live_agent",
            headline=_finding_headline(worst, world),
        )

    def _minimize(
        self,
        world: World,
        subject: Subject,
        baseline: RecordedRun,
        fact: dict[str, Any] | None,
        kind: Expect | None,
    ) -> tuple[World, dict[str, Any]]:
        def reproduces(candidate: World) -> bool:
            wr = WorldResult(candidate, self.base_validity)
            run_trial = self._trial(subject, candidate, baseline, fact, wr, "min")
            try:
                outcome = run_trial(0)
            except Exception:
                return False
            if not is_bad(outcome) or not wr.judged:
                return False
            return kind is None or wr.judged[0].expectation.kind is kind

        if subject.stochastic:
            noisy = minimize_path_noisy(self.base, world.path, lambda w: reproduces(w))
            path_world = self.base
            for m in noisy.path:
                path_world = path_world.apply(m)
            return path_world, {
                "minimized": True,
                "mode": "mutation path, noise tolerant",
                "status": noisy.status.value,
                "minimal": noisy.minimal,
                "runs": noisy.runs,
                "note": noisy.note,
                "documents_before": len(documents_of(world.state)),
                "documents_after": len(documents_of(path_world.state)),
            }
        minimized = minimize_world(
            self.spec,
            world,
            self.state,
            reproduces,
            max_attempts=self.config.minimization_max_attempts,
        )
        return minimized.world, {
            "minimized": True,
            "mode": "corpus (frozen index statistics: kept ranks do not move)",
            "complete": minimized.complete,
            "attempts": minimized.attempts,
            "documents_before": minimized.atoms_before,
            "documents_after": minimized.atoms_after,
            "changed_documents": minimized.changed_atoms,
        }

    def _artifact(
        self,
        case_id: str,
        number: int,
        world: World,
        subject: Subject,
        baseline: RecordedRun,
        run: RecordedRun,
        verdict: Judged | None,
        fact: dict[str, Any] | None,
    ) -> ReplayArtifact:
        stats = self.stats.restricted(
            terms_of(world.state.entities(COLLECTION))
            | {t for q in [self.task.question] for t in tokenize(q)}
            | {t for query in baseline.queries() for t in tokenize(query["query"])}
            | {t for query in run.queries() for t in tokenize(query["query"])}
        )
        return ReplayArtifact(
            pack=PACK,
            case_id=f"{case_id}:{number}",
            world=world.to_json(),
            host={"fidelity": "SIMULATED", "index_stats": stats.to_json()},
            inputs={
                "task": self.task.model_dump(mode="json"),
                "subject": subject.label.model_dump(mode="json"),
                "stochastic": subject.stochastic,
                "baseline_run": baseline.model_dump(mode="json"),
                "world_run": run.model_dump(mode="json"),
                "fact": fact,
            },
            expected={
                **_expected(verdict),
                "trace_reproduced": True,
                **(
                    {"subject_rerun_same_report": True}
                    if subject.label.kind == "stand_in" and run.seed is not None
                    else {}
                ),
            },
        )

    # -- frozen mode ---------------------------------------------------------------------------

    def check_frozen(self, recorded: RecordedRun) -> CaseReport:
        started = time.monotonic()
        config, task = self.config, self.task
        subject = Subject(
            recorded.subject, False, lambda w, s: recorded, SubjectKind.FROZEN_ARTIFACT
        )
        gate = self._baseline_gate(recorded)
        if gate and not config.allow_failing_baseline:
            return self._inconclusive_baseline(subject, started, gate, [recorded])
        hints = hints_from_run(recorded, task.answer_type, task.question, documents_of(self.state))
        if config.declared_hints:
            hints = hints.merged(config.declared_hints)
        fact = _fact_args(hints)
        budget = Budget(attempts=config.attempts, seconds=config.seconds)
        results: dict[str, WorldResult] = {}
        fidelity = self.frozen_fidelity(recorded)
        qualification = (
            f"ranking-dependent: the simulated retrieval returned the recorded first result in "
            f"{fidelity['same_top1']} of {fidelity['queries']} recorded queries"
        )

        def evaluate(candidate: Candidate, validity: Validity) -> Evaluation:
            world = candidate.world
            wr = WorldResult(world, validity)
            results[world.fingerprint()] = wr
            if fact is None:
                return Evaluation(Verdict.INCONCLUSIVE, validity, reason="no fact span")
            wr.screening, wr.screening_basis = self.screen(world, recorded, fact)
            if wr.screening in ("STALE", "UNSCREENABLE", "RIGHT_IF_UNCHANGED"):
                wr.screening_basis += f" ({qualification})"
            lists = self.replay_queries(world, recorded.queries())
            wr.observed_ids = sorted({i for ids in lists for i in ids})
            verdict = judge(world, recorded, recorded, fact, task.answer_type)
            wr.judged = [verdict]
            self._note_cannot_judge(world, recorded, verdict, 0)
            wr.role, wr.role_basis = verdict.expectation.role, verdict.expectation.basis
            wr.runs = [recorded]
            docs = documents_of(world.state)
            targets = [i for i, d in docs.items() if (d.get("provenance") or {}).get("kind")]
            wr.unobservable = (
                bool(targets)
                and not any(t in wr.observed_ids for t in targets)
                and not any((docs[t]["provenance"]).get("kind") == "retract" for t in targets)
            )
            if wr.unobservable:
                return Evaluation(
                    Verdict.INCONCLUSIVE, validity, detail=wr, reason="unobservable_change"
                )
            objective = verdict.invariant.outcome is Outcome.NOT_MET or (
                verdict.expectation.kind is Expect.ABSTAIN_OR_FLAG
                and verdict.constructive.outcome is Outcome.NOT_MET
            )
            wr.outcomes = [
                RunOutcome(Outcome.NOT_MET if objective else Outcome.MET, violated=objective)
            ]
            if objective:
                return Evaluation(Verdict.DISAGREE, validity, detail=wr)
            return Evaluation(Verdict.AGREE, validity, detail=wr)

        mutators = list(config.mutators) if config.mutators is not None else all_mutators()
        result = search(
            self.spec,
            self.base,
            hints,
            mutators,
            evaluate,
            budget=budget,
            seed=config.seed,
            depth=1,
            stop_on_first=False,
        )
        findings = [
            self._frozen_finding(i, f.candidate.world, f.validity, recorded, fact, results)
            for i, f in enumerate(result.findings[: config.max_findings], start=1)
        ]
        self._frozen_fidelity = fidelity
        return self._report(
            subject,
            started,
            result,
            results,
            findings,
            [recorded],
            [],
            check_citations(recorded.report, documents_of(self.state)).to_json(),
            hints,
            budget,
            gate,
            mode="frozen",
        )

    def frozen_fidelity(self, recorded: RecordedRun) -> dict[str, Any]:
        """How closely the simulated retrieval reproduces the recorded results: for each recorded
        query, whether the first result and the whole result set match what the agent was shown.
        Citation findings do not depend on it; exposure classes (what a changed corpus would show
        the agent) do. Reported as counts and a share, with no threshold."""
        recorded_lists = recorded.queries()
        ours = self.replay_queries(self.base, recorded_lists)
        total = len(recorded_lists)
        same_top = sum(
            1 for q, mine in zip(recorded_lists, ours, strict=True) if mine[:1] == q["ids"][:1]
        )
        same_set = sum(
            1 for q, mine in zip(recorded_lists, ours, strict=True) if set(mine) == set(q["ids"])
        )
        overlap = sum(
            len(set(mine) & set(q["ids"])) / max(1, len(q["ids"]))
            for q, mine in zip(recorded_lists, ours, strict=True)
        )
        return {
            "queries": total,
            "same_top1": same_top,
            "same_top5_set": same_set,
            "mean_overlap_at_5": round(overlap / total, 3) if total else None,
            "top1_share": round(same_top / total, 3) if total else None,
            "depends_on_it": [
                "exposure classes (STALE, UNSCREENABLE, RIGHT_IF_UNCHANGED)",
                "UNOBSERVABLE",
            ],
            "does_not_depend_on_it": ["a cited document or quote that the world lacks or retracts"],
        }

    def _frozen_finding(
        self,
        number: int,
        world: World,
        validity: Validity,
        recorded: RecordedRun,
        fact: dict[str, Any] | None,
        results: dict[str, WorldResult],
    ) -> Finding:
        case_id = f"{self.task.id}:{recorded.subject.name}"
        judge(world, recorded, recorded, fact, self.task.answer_type)

        def reproduces(candidate: World) -> bool:
            v = judge(candidate, recorded, recorded, fact, self.task.answer_type)
            return v.invariant.outcome is Outcome.NOT_MET or (
                v.expectation.kind is Expect.ABSTAIN_OR_FLAG
                and v.constructive.outcome is Outcome.NOT_MET
            )

        minimized = minimize_world(self.spec, world, self.state, reproduces)
        final = minimized.world
        shown = judge(final, recorded, recorded, fact, self.task.answer_type)
        self.artifacts[f"{case_id}:{number}"] = self._artifact(
            case_id,
            number,
            final,
            Subject(recorded.subject, False, lambda w, s: recorded, SubjectKind.FROZEN_ARTIFACT),
            recorded,
            recorded,
            shown,
            fact,
        )
        self.exports[f"{case_id}:{number}"] = export_case(self.artifacts[f"{case_id}:{number}"])
        docs_after = [
            {
                "id": i,
                "title": d.get("title"),
                "date": d.get("date"),
                "provenance": d.get("provenance"),
                "text": d["text"],
            }
            for i, d in sorted(documents_of(final.state).items())
        ]
        return Finding(
            finding_id=f"{case_id}:{number}",
            world_id=final.fingerprint(),
            validity=validity_record(self.spec.validate_world(final.state, world.path)),
            oracles=_oracle_records(shown),
            world_diff=diff_states(self.state, final.state),
            mutation_path=_path(world),
            divergence={
                "scope": "this recorded report on this world; not a statement about the agent "
                "(the report is not regenerated)",
                "subject": recorded.subject.model_dump(mode="json"),
                "question": self.task.question,
                "recorded_report": recorded.report.model_dump(mode="json"),
                "expectation": shown.expectation.to_json(),
                "citations": shown.citations,
                "oracle_messages": shown.constructive.messages + shown.invariant.messages,
                "documents_in_world": docs_after,
                "reference_trust": f"gold {self.task.gold!r}: {self.task.gold_basis}"
                if self.task.gold is not None
                else "no gold answer was given; the recorded answer is the reference",
                "depends_on_simulated_ranking": False,
                "reproduces_on_shown_world": bool(reproduces(final)),
                "found_on_world": world.fingerprint(),
                "shown_world": final.fingerprint(),
                "shown_world_is_minimized": True,
            },
            fidelity=FidelityRecord(found_on="SIMULATED", engine="frozen BM25 (isitright)"),
            replay=ReplayRecord(artifact=f"{number}.replay.json"),
            export=f"{number}.eval-case.json",
            minimization={
                "minimized": True,
                "mode": "corpus (frozen index statistics)",
                "complete": minimized.complete,
                "attempts": minimized.attempts,
                "documents_before": minimized.atoms_before,
                "documents_after": minimized.atoms_after,
            },
            mode="frozen_trace",
            headline=_finding_headline(shown, world),
        )

    # -- reports ---------------------------------------------------------------------------------

    def _unsupported(
        self, subject: Subject, started: float, reason: str, runs: list[RecordedRun]
    ) -> CaseReport:
        return self._shell(
            subject, started, DivergenceStatus.UNSUPPORTED, reason, runs, search_result=None
        )

    def _inconclusive_baseline(
        self, subject: Subject, started: float, reason: str, runs: list[RecordedRun]
    ) -> CaseReport:
        return self._shell(
            subject, started, DivergenceStatus.INCONCLUSIVE, reason, runs, search_result=None
        )

    def _shell(
        self,
        subject: Subject,
        started: float,
        status: DivergenceStatus,
        reason: str,
        runs: list[RecordedRun],
        search_result: SearchResult | None,
    ) -> CaseReport:
        return CaseReport(
            case_id=f"{self.task.id}:{subject.label.name}",
            pack=PACK,
            task=self.task.question,
            subject_kind=subject.kind.value,
            divergence_status=status,
            validity=ValidityRecord(status="NOT_ASSESSED"),
            execution_fidelity=FidelityRecord(
                found_on="SIMULATED", engine="frozen BM25 (isitright)"
            ),
            oracles=[],
            search=SearchRecord(seed=self.config.seed, attempts=0, valid_candidates=0, executed=0),
            inputs={"task_id": self.task.id},
            assumptions=list(ASSUMPTIONS),
            headline=headline_for(status, reason),
            elapsed_seconds=time.monotonic() - started,
            extensions={
                PACK: {
                    "mode": "baseline",
                    "subject": subject.label.model_dump(mode="json"),
                    "reason": reason,
                    "baseline_reports": [r.report.model_dump(mode="json") for r in runs],
                    "gold": {"answer": self.task.gold, "trust": self.task.gold_basis},
                }
            },
        )

    def _report(
        self,
        subject: Subject,
        started: float,
        result: SearchResult,
        results: dict[str, WorldResult],
        findings: list[Finding],
        baseline_runs: list[RecordedRun],
        baseline_outcomes: list[RunOutcome],
        base_citations: dict[str, Any],
        hints: Hints,
        budget: Budget,
        gate: str | None,
        *,
        mode: str,
    ) -> CaseReport:
        task = self.task
        worlds, flips = self._world_records(results)
        controls_input = [
            (wr.role, [j.outcome for j in wr.judged])
            for wr in results.values()
            if wr.judged and not wr.unobservable
        ]
        status_c, detail_c = (
            controls_status(controls_input)
            if mode == "live"
            else (
                "NOT_APPLICABLE",
                "frozen replay: the report is not regenerated, so a control cannot be reached",
            )
        )
        executed = result.executed
        if findings:
            status = DivergenceStatus.COUNTEREXAMPLE_FOUND
        elif executed == 0:
            status = DivergenceStatus.INCONCLUSIVE
        else:
            status = DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
        unobservable = sorted(
            wr.world.path[-1].description
            for wr in results.values()
            if wr.unobservable and wr.world.path
        )
        summary = (
            f"{len(findings)} world(s) where the report and the expected behavior disagree"
            if findings
            else "no disagreement found within the budget"
        )
        if unobservable:
            summary += f"; {len(unobservable)} change(s) no query can retrieve (UNOBSERVABLE)"
        if self.cannot_judge_rows:
            summary += f"; {len(self.cannot_judge_rows)} run(s) not judged (CANNOT_JUDGE)"
        if status_c == "NOT_DISCRIMINATING":
            summary += "; controls never reached (NOT_DISCRIMINATING)"
        level = base_citations.get("level_reached")
        if level in ("NONE", "L0") and not baseline_runs[0].report.abstained():
            summary += f"; the baseline report's own citations reach only level {level}"
        first = findings[0] if findings else None
        base_valid = validity_record(self.base_validity)
        record = SearchRecord(
            **{
                **result.accounting(),
                "hint_use": [
                    HintUse(name=h.name, kind=h.kind, provenance=h.provenance.value) for h in hints
                ],
            }
        )
        oracle_outcome: Any = "NOT_MET" if findings else ("MET" if executed else None)
        return CaseReport(
            case_id=f"{task.id}:{subject.label.name}",
            pack=PACK,
            task=task.question,
            subject_kind=subject.kind.value,
            divergence_status=status,
            validity=first.validity if first else base_valid,
            execution_fidelity=first.fidelity
            if first
            else FidelityRecord(found_on="SIMULATED", engine="frozen BM25 (isitright)"),
            oracles=[
                OracleRecord(
                    name="constructive reference over the corpus",
                    kind="CONSTRUCTIVE",
                    outcome=oracle_outcome,
                    description=(
                        "what the report should say after the mutation, computed from the "
                        "documents it added or changed"
                    ),
                    limits=ORACLE_LIMITS,
                ),
                OracleRecord(
                    name="citations_exist_and_quote",
                    kind="INVARIANT",
                    description=(
                        "every cited id exists (L0) and every quote occurs in its document (L1)"
                    ),
                    limits=["L2 (support of the claim) is not judged"],
                ),
            ],
            stability=stability(
                baseline_outcomes,
                [o for wr in results.values() for o in wr.outcomes][: len(baseline_outcomes) or 1],
                len(baseline_outcomes) or 1,
            )
            if subject.stochastic and baseline_outcomes
            else None,
            search=record,
            findings=findings,
            worlds=worlds,
            controls=ControlsRecord(status=status_c, detail=detail_c),  # type: ignore[arg-type]
            comparison_policy={
                "answer_type": task.answer_type,
                "normalization": (
                    "string: casefold, strip punctuation and articles; number: first number, "
                    "separators removed; date: ISO"
                ),
                "conflict_flags": (
                    "the agent's own flags when present, else a keyword rule (stated per result)"
                ),
                "citation_levels": "L0 id exists, L1 quote in document; L2 not judged",
            },
            inputs={"task_id": task.id, "question": task.question},
            original_state={
                "documents": len(documents_of(self.state)),
                "baseline_answer": baseline_runs[0].report.answer,
                "baseline_citations": base_citations,
            },
            assumptions=list(ASSUMPTIONS),
            checked_rules=sorted(set(self.base_validity.checked_rules)),
            unused_rules=[r.name for r in self.spec.python_constraints],
            errors=[{"detail": e} for e in result.errors[:10]],
            headline=headline_for(status, summary),
            elapsed_seconds=time.monotonic() - started,
            extensions={
                PACK: {
                    "mode": mode,
                    "subject": subject.label.model_dump(mode="json"),
                    "subject_statement": _subject_statement(subject.label, mode),
                    "retrieval": {
                        "scorer": RETRIEVER_STATEMENTS[self.stats.retriever],
                        "retriever": self.stats.retriever,
                        "documents": self.stats.n,
                        "tools": ["search", "open"],
                        "fidelity": "SIMULATED",
                    },
                    "gold": {"answer": task.gold, "trust": task.gold_basis},
                    "baseline": {
                        "runs": len(baseline_runs),
                        "reports": [r.report.model_dump(mode="json") for r in baseline_runs],
                        "gate": gate,
                        "citations": base_citations,
                        "queries": baseline_runs[0].queries(),
                        "opened": baseline_runs[0].opened(),
                    },
                    "flip_table": flips,
                    **({"frozen_fidelity": self._frozen_fidelity} if mode == "frozen" else {}),
                    "cannot_judge": self._cannot_judge_summary(),
                    "unobservable_changes": unobservable,
                    "proposed_classification": [
                        {"finding": f.finding_id, **_classify(f)} for f in findings
                    ],
                    "classification_label": (
                        "a proposal by the implementing assistant; attribution stays UNDETERMINED"
                    ),
                    "budget": budget.to_json(),
                }
            },
        )

    def _cannot_judge_summary(self, per_family: int = 3, width: int = 300) -> dict[str, Any]:
        """Counts per mutator and a few truncated examples; the full list is cannot-judge.jsonl.

        A run is not judged when its answer cannot be read as the declared kind (prose with two
        numbers, a negation) or when the expected behavior is undefined. Unparseable answers can
        correlate with the mutation (an agent that notices a conflict may hedge in prose), so the
        count per mutator is shown: a high count in one family means the finding is incomplete
        there, not that the agent was right.
        """
        by_family: dict[str, int] = {}
        examples: dict[str, list[dict[str, Any]]] = {}
        for row in self.cannot_judge_rows:
            family = row["family"]
            by_family[family] = by_family.get(family, 0) + 1
            if len(examples.setdefault(family, [])) < per_family:
                answer = row["answer"]
                shown = answer if answer is None or len(answer) <= width else answer[:width] + "..."
                examples[family].append(
                    {"answer": shown, "reason": row["reason"], "mutations": row["mutations"]}
                )
        return {
            "runs": len(self.cannot_judge_rows),
            "by_mutator": dict(sorted(by_family.items())),
            "examples": examples,
            "answers_truncated_at": width,
            "full_list": "cannot-judge.jsonl, written beside the report"
            if self.cannot_judge_rows
            else None,
        }

    def _world_records(
        self, results: dict[str, WorldResult]
    ) -> tuple[list[WorldRecord], dict[str, Any]]:
        records: list[WorldRecord] = []
        flips: dict[str, dict[str, Any]] = {}
        for fp, wr in results.items():
            family = "+".join(m.family for m in wr.world.path) or "baseline"
            judged = wr.judged
            outcome = judged[0].outcome.value if judged else None
            behaviors = [j.behavior.value for j in judged]
            counts = {"runs": len(wr.outcomes)}
            records.append(
                WorldRecord(
                    id=fp,
                    role=wr.role.value if judged else "unjudgeable",
                    description=" + ".join(m.description for m in wr.world.path) or "baseline",
                    validity=validity_record(wr.validity, wr.unobservable),
                    oracle_outcome=outcome,  # type: ignore[arg-type]
                    role_basis=wr.role_basis,
                    counts=counts,
                    mutation_path=_path(wr.world),
                    screening=ScreeningRecord(
                        screening_class=wr.screening,  # type: ignore[arg-type]
                        basis=wr.screening_basis,
                    )
                    if wr.screening
                    else None,
                    run_status="NOT_RUN" if wr.not_run else "RUN",
                    not_run_reason=wr.not_run,
                )
            )
            if not judged:
                continue
            row = flips.setdefault(
                family,
                {
                    "worlds": 0,
                    "answer_changed": 0,
                    "not_met": 0,
                    "cannot_judge": 0,
                    "runs_judged": 0,
                    "runs_not_judged": 0,
                    "unobservable": 0,
                    "behaviors": {},
                    "observations": {
                        "worlds_with_an_added_document": 0,
                        "appeared": 0,
                        "claim_exposed": 0,
                        "claim_exposure_unknown": 0,
                        "adopted": 0,
                        "cited": 0,
                    },
                },
            )
            row["worlds"] += 1
            row["answer_changed"] += int(any(j.answer_changed for j in judged))
            row["not_met"] += int(any(j.outcome is Outcome.NOT_MET for j in judged))
            row["unobservable"] += int(wr.unobservable)
            row["cannot_judge"] += int(
                any(j.constructive.outcome is Outcome.CANNOT_JUDGE for j in judged)
            )
            # the denominators: a family with 2 judged and 18 unjudged runs is not one with 20
            unjudged = sum(j.constructive.outcome is Outcome.CANNOT_JUDGE for j in judged)
            row["runs_not_judged"] += unjudged
            row["runs_judged"] += len(judged) - unjudged
            targets = (judged[0].observations or {}).get("targets") or {}
            if targets:
                seen = row["observations"]
                seen["worlds_with_an_added_document"] += 1
                for key in ("appeared", "claim_exposed", "adopted", "cited"):
                    seen[key] += int(any(o[key] is True for o in targets.values()))
                seen["claim_exposure_unknown"] += int(
                    any(o["claim_exposed"] is None for o in targets.values())
                )
            for b in behaviors[:1]:
                row["behaviors"][b] = row["behaviors"].get(b, 0) + 1
        return records, flips


def _subject_statement(label: SubjectLabel, mode: str) -> str:
    """Who produced the result and how it was used. A stand-in is never a real agent, and a
    recorded run is replayed, never run again."""
    who = {
        "stand_in": "stand-in agent written by Claude, not a real research agent",
        "recorded": "a recorded agent run",
        "live_agent": "a live agent run by the owner",
    }[label.kind]
    if mode == "frozen":
        return f"{who}; replayed frozen: the report is not regenerated"
    return who


def _cost_of(run: RecordedRun) -> Cost:
    c = run.cost
    return Cost(
        int(c.get("input_tokens", 0)),
        int(c.get("output_tokens", 0)),
        float(c.get("money", 0.0)),
        float(c.get("seconds", 0.0)),
    )


def _fact_args(hints: Hints) -> dict[str, Any] | None:
    found = hints.of("fact_span")
    return dict(found[0].args) if found else None


def _cited(run: RecordedRun) -> set[str]:
    return set(run.report.cited_ids()) | set(run.opened())


def _oracle_records(verdict: Judged | None) -> list[OracleRecord]:
    if verdict is None:
        return []
    return [
        OracleRecord(
            name=verdict.constructive.name,
            kind=verdict.constructive.kind,
            outcome=verdict.constructive.outcome.value,
            description="; ".join(verdict.constructive.messages),
            limits=ORACLE_LIMITS,
        ),
        OracleRecord(
            name=verdict.invariant.name,
            kind="INVARIANT",
            outcome=verdict.invariant.outcome.value,
            description="; ".join(verdict.invariant.messages),
            limits=["L2 (support of the claim) is not judged"],
        ),
    ]


def _expected(verdict: Judged | None) -> dict[str, Any]:
    if verdict is None:
        return {}
    return {
        "outcome": verdict.outcome.value,
        "expectation": verdict.expectation.kind.value,
        "behavior": verdict.behavior.value,
    }


def _finding_headline(verdict: Judged | None, world: World) -> str:
    family = world.path[-1].family if world.path else "baseline"
    if verdict is None:
        return f"The report and the expected behavior disagree after a {family} mutation"
    return (
        f"The report and the expected behavior disagree after a {family} mutation "
        f"({verdict.expectation.kind.value.lower()}, behavior {verdict.behavior.value.lower()})"
    )


def _classify(finding: Finding) -> dict[str, str]:
    """A proposal for the owner, labeled as such. Attribution stays UNDETERMINED."""
    d = finding.divergence
    family = finding.mutation_path[-1].family if finding.mutation_path else ""
    citations = d.get("citations") or {}
    if citations.get("l0_failures"):
        return {"class": "likely agent defect", "why": "it cites a document that does not exist"}
    if citations.get("l1_failures"):
        return {
            "class": "likely agent defect",
            "why": "a quote it gives is not in the cited document",
        }
    if family in ("plant", "contradict"):
        return {
            "class": "likely agent defect",
            "why": "it followed a conflicting document without stating the conflict",
        }
    if family == "supersede":
        return {
            "class": "likely agent defect or ambiguous question",
            "why": "it did not use or mention the newer edition",
        }
    if family == "retract":
        return {"class": "likely agent defect", "why": "it still rests on a retracted source"}
    if family == "remove":
        return {
            "class": "likely agent defect or corpus artifact",
            "why": "it answers although the source it relied on is gone",
        }
    if family in ("reorder", "snippets"):
        return {
            "class": "likely retrieval defect",
            "why": "it is sensitive to the order or snippet of results",
        }
    return {"class": "ambiguous", "why": "no rule applies"}


def spec_of(audit: ResearchAudit) -> WorldSpec:
    return audit.spec


__all__ = [
    "AuditConfig",
    "ResearchAudit",
    "ResearchInputError",
    "Subject",
    "normalize",
    "sha256_text",
]
