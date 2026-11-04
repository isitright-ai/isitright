"""Frozen audit: replay a recorded program on generated worlds and compare it with the gold program.

A finding is scoped to the program: "this program disagrees with the reference on world X". It says
nothing about the agent that wrote it until a live confirmation (`live.py`) is recorded.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isitright.core.constraints import Validity
from isitright.core.entities import ModelError
from isitright.core.evidence import (
    CaseReport,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    MutationRecord,
    OracleRecord,
    ReplayRecord,
    SearchRecord,
    ValidityRecord,
    headline_for,
    safe_detail,
)
from isitright.core.families import default_mutators
from isitright.core.hints import Hints
from isitright.core.minimize import minimize_world
from isitright.core.mutations import Candidate, World
from isitright.core.replay import ReplayArtifact
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.subjects import SubjectKind
from isitright.core.world import State, diff_states, sha256_text
from isitright.packs.data.comparison import DataComparator, undefined_answer
from isitright.packs.data.hints import harvest_program_hints
from isitright.packs.data.host import DataHost, RunResult
from isitright.packs.data.mapping import (
    ROW_KEY,
    UnsupportedTable,
    read_frame,
    representability_rule,
    round_trip_problems,
    schema_from_frames,
    state_from_frames,
)
from isitright.packs.data.programs import RecordedProgram, scan_program
from isitright.packs.data.task import DataTask

PACK = "data"
GOLD_LIMITS = [
    "the gold program is an implementation written for this task; it can be wrong or ambiguous",
    "it follows the mutated world, so a disagreement means the two programs read the data "
    "differently, not that the data is wrong",
]


@dataclass
class AuditConfig:
    seed: int = 0
    attempts: int = 300
    depth: int = 2
    findings: int = 1
    minimization_max_attempts: int = 300
    timeout_seconds: float = 30.0
    memory_mb: int | None = 2048
    trust_code: bool = False
    max_rows: int | None = None
    reuse: int = 1
    parallel: bool = True
    """Run the gold and the program of a world in two processes at once (False: one at a time,
    for a machine short of memory)."""
    """Runs per host process (1: a new process per run)."""


class AuditInputError(ValueError):
    """The task or the data cannot be audited; the message says why."""


def validity_record(validity: Validity) -> ValidityRecord:
    return ValidityRecord(
        status=validity.status.value,
        tiers=[t.value for t in validity.tiers],
        problems=list(validity.problems),
        notes=list(validity.notes),
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


@dataclass
class Pair:
    gold: RunResult
    program: RunResult


@dataclass
class Prepared:
    spec: WorldSpec
    base: State
    frames: dict[str, Any]


class DataAudit:
    """Prepares a task once (frames, schema, base world) and checks recorded programs against it."""

    def __init__(self, task: DataTask, config: AuditConfig | None = None) -> None:
        self.task = task
        self.config = config or AuditConfig()
        self.comparator = DataComparator(task.policy)
        self.prepared = self._prepare()
        self.host = DataHost(
            self.prepared.spec.schema,
            trust_code=self.config.trust_code,
            timeout_seconds=self.config.timeout_seconds,
            memory_mb=self.config.memory_mb,
            outputs=task.outputs,
            reuse=self.config.reuse,
        )
        self._gold_cache: dict[str, RunResult] = {}
        self.artifacts: dict[str, ReplayArtifact] = {}
        self._pool = ThreadPoolExecutor(max_workers=2 if self.config.parallel else 1)

    def close(self) -> None:
        self._pool.shutdown(wait=True)
        self.host.close()

    def __enter__(self) -> DataAudit:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _prepare(self) -> Prepared:
        import tempfile

        task = self.task
        try:
            frames = {f.table: read_frame(task.data_dir / f.file) for f in task.files}
            limit = self.config.max_rows or task.max_rows
            schema = schema_from_frames(frames, task.files)
            if limit is not None:
                for table, frame in frames.items():
                    if len(frame) > limit:
                        raise UnsupportedTable(f"{table}: {len(frame)} rows (limit {limit})")
        except (UnsupportedTable, ValueError, OSError) as error:
            raise AuditInputError(str(error)) from error
        base = state_from_frames(frames, schema, task.files)
        with tempfile.TemporaryDirectory(prefix="isitright-rt-") as scratch:
            problems = round_trip_problems(base, schema, frames, Path(scratch))
        if problems:
            raise AuditInputError("; ".join(problems))
        try:
            spec = WorldSpec(
                id=task.id,
                schema=schema,
                constraints=list(task.constraints),
                python_constraints=[representability_rule(schema)],
            )
        except ModelError as error:
            raise AuditInputError(
                f"the declared constraints do not fit the data: {error}"
            ) from error
        return Prepared(spec, base, frames)

    # --- running ------------------------------------------------------------------------------

    def run_pair(self, program_code: str, state: State) -> Pair:
        key = state.fingerprint()
        cached = self._gold_cache.get(key)
        if cached is None:
            gold_future = self._pool.submit(self.host.run, self.task.gold, state)
            program_future = self._pool.submit(self.host.run, program_code, state)
            gold, program = gold_future.result(), program_future.result()
            self._gold_cache[key] = gold
            return Pair(gold, program)
        return Pair(cached, self.host.run(program_code, state))

    def judge(self, pair: Pair) -> tuple[Verdict, str, dict[str, Any]]:
        """Verdict for one world: AGREE, DISAGREE, or why the world cannot be judged."""
        gold, program = pair.gold, pair.program
        detail: dict[str, Any] = {
            "gold_status": gold.status,
            "program_status": program.status,
            "gold_answer": gold.answer()[0],
            "program_answer": program.answer()[0],
            "program_error": program.error,
        }
        if gold.status != "ok":
            return Verdict.INCONCLUSIVE, f"reference_{gold.status}", detail
        if undefined_answer(gold.answer()[0]):
            return Verdict.INCONCLUSIVE, "reference_undefined", detail
        if program.status in {"timeout", "memory"}:
            return Verdict.ERROR, f"program_{program.status}", detail
        if program.status == "unsupported":
            return Verdict.ERROR, "program_blocked", {**detail, "violations": program.violations}
        if program.status == "error":
            detail["difference"] = f"the program raised: {program.error}"
            return Verdict.DISAGREE, "program_error", detail
        outcome = self.comparator.compare(gold.answer()[0], program.answer()[0])
        if outcome.inconclusive:
            return (
                Verdict.INCONCLUSIVE,
                "cannot_judge",
                {**detail, "difference": outcome.difference},
            )
        detail["difference"] = outcome.difference
        return (Verdict.AGREE if outcome.matches else Verdict.DISAGREE), "", detail

    # --- the audit ----------------------------------------------------------------------------

    def check_frozen(
        self, program: RecordedProgram, progress: Callable[[str], None] | None = None
    ) -> CaseReport:
        started = time.monotonic()
        config, task, p = self.config, self.task, self.prepared
        case_id = f"{task.id}:{program.program_id}"
        scan = scan_program(program.code, {f.file for f in task.files})
        if scan.unsupported:
            return self._report(
                program,
                started,
                DivergenceStatus.UNSUPPORTED,
                None,
                f"Unsupported program: {safe_detail(scan.unsupported[0])}",
                errors=[
                    {"code": "UNSUPPORTED_PROGRAM", "message": m, "phase": "scan"}
                    for m in scan.unsupported
                ],
                flags=scan.flags,
            )
        base_pair = self.run_pair(program.code, p.base)
        again = self.host.run(program.code, p.base)
        blocked = dict.fromkeys([*base_pair.program.violations, *base_pair.gold.violations])
        scan.flags.extend(f"blocked and survived: {v}" for v in blocked)
        for label, run in (("gold program", base_pair.gold), ("program", base_pair.program)):
            if run.status != "ok":
                why = run.error or "; ".join(run.violations[:3]) or run.stderr[-200:]
                reason = f"the {label} does not run on the original data ({run.status}): {why}"
                status = (
                    DivergenceStatus.UNSUPPORTED
                    if label == "program" or run.status != "ok"
                    else DivergenceStatus.INCONCLUSIVE
                )
                return self._report(
                    program,
                    started,
                    status,
                    None,
                    f"Unsupported: {safe_detail(reason)}",
                    errors=[{"code": "BASELINE_RUN", "message": reason, "phase": "baseline"}],
                    flags=scan.flags,
                    base_pair=base_pair,
                )
        stable = self.comparator.compare(base_pair.program.answer()[0], again.answer()[0])
        if not stable.matches:
            return self._report(
                program,
                started,
                DivergenceStatus.INCONCLUSIVE,
                None,
                "Inconclusive: two runs on the original data gave different answers "
                "(the program is nondeterministic)",
                errors=[
                    {
                        "code": "NONDETERMINISTIC",
                        "message": stable.difference or "",
                        "phase": "baseline",
                    }
                ],
                flags=scan.flags,
                base_pair=base_pair,
            )
        verdict, reason, detail = self.judge(base_pair)
        if verdict is Verdict.INCONCLUSIVE:
            return self._report(
                program,
                started,
                DivergenceStatus.INCONCLUSIVE,
                None,
                f"Inconclusive: the answers on the original data cannot be compared ({reason})",
                errors=[
                    {
                        "code": "CANNOT_JUDGE",
                        "message": str(detail.get("difference")),
                        "phase": "baseline",
                    }
                ],
                flags=scan.flags,
                base_pair=base_pair,
            )
        if verdict is Verdict.DISAGREE:
            return self._report(
                program,
                started,
                DivergenceStatus.INCONCLUSIVE,
                None,
                "Inconclusive: the program already disagrees with the reference on the original "
                "data, so there is no baseline to audit",
                errors=[
                    {
                        "code": "BASELINE_DISAGREES",
                        "message": str(detail.get("difference")),
                        "phase": "baseline",
                    }
                ],
                flags=scan.flags,
                base_pair=base_pair,
            )
        hints = Hints(task.hints).merged(
            harvest_program_hints(program.code, p.spec.schema, task.files, question=task.question)
        )
        hints.validate(p.spec.schema)

        def evaluate(candidate: Candidate, validity: Validity) -> Evaluation:
            pair = self.run_pair(program.code, candidate.world.state)
            outcome, why, info = self.judge(pair)
            return Evaluation(outcome, validity, info, why)

        budget = Budget(attempts=config.attempts)
        result = search(
            p.spec,
            World(p.base),
            hints,
            default_mutators(),
            evaluate,
            budget=budget,
            seed=config.seed,
            depth=config.depth,
            stop_on_first=config.findings <= 1,
            progress=progress,
        )
        findings = [
            self._finding(
                program, case_id, n, f.candidate.world, f.validity, f.evaluation, hints, scan.flags
            )
            for n, f in enumerate(result.findings[: config.findings], 1)
        ]
        status = (
            DivergenceStatus.COUNTEREXAMPLE_FOUND
            if findings
            else DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
        )
        summary = (
            f"the program and the reference give different answers on {len(findings)} "
            f"minimized world{'s' if len(findings) != 1 else ''}"
            if findings
            else f"no disagreement in {result.executed} worlds executed ({result.attempts} tried)"
        )
        return self._report(
            program,
            started,
            status,
            result,
            headline_for(status, summary),
            findings=findings,
            flags=scan.flags,
            base_pair=base_pair,
            hints=hints,
        )

    def _finding(
        self,
        program: RecordedProgram,
        case_id: str,
        number: int,
        world: World,
        validity: Validity,
        evaluation: Evaluation,
        hints: Hints,
        flags: list[str],
    ) -> Finding:
        p, config = self.prepared, self.config

        def reproduces(candidate: World) -> bool:
            try:
                pair = self.run_pair(program.code, candidate.state)
                return self.judge(pair)[0] is Verdict.DISAGREE
            except Exception:
                return False

        minimized = minimize_world(
            p.spec,
            world,
            p.base,
            reproduces,
            referenced=[f.table for f in self.task.files],
            max_attempts=config.minimization_max_attempts,
        )
        final = minimized.world
        pair = self.run_pair(program.code, final.state)
        _, _, detail = self.judge(pair)
        final_validity = p.spec.validate_world(final.state, world.path)
        self.artifacts[f"{case_id}:{number}"] = self.replay_artifact(
            program, case_id, final, detail
        )
        return Finding(
            finding_id=f"{case_id}:{number}",
            world_id=world.fingerprint(),
            validity=validity_record(final_validity),
            oracles=[
                OracleRecord(
                    name="gold program",
                    kind="REFERENCE_PROGRAM",
                    outcome="NOT_MET",
                    description="a reference program run on the same world with the same host",
                    limits=GOLD_LIMITS,
                )
            ],
            world_diff=diff_states(p.base, final.state),
            mutation_path=_path(world),
            divergence={
                "scope": "this program on this world; not a statement about the agent",
                "reproduces": self.judge(pair)[0] is Verdict.DISAGREE,
                "difference": detail.get("difference"),
                "gold_answer": detail.get("gold_answer"),
                "program_answer": detail.get("program_answer"),
                "program_status": detail.get("program_status"),
                "program_error": detail.get("program_error") or None,
                "data_files": self.data_files(final.state),
                "gold_program": self.task.gold,
                "program_flags": flags,
            },
            fidelity=self.fidelity(pair),
            replay=ReplayRecord(artifact=f"{number}.replay.json"),
            minimization={
                "complete": minimized.complete,
                "attempts": minimized.attempts,
                "rows_before": minimized.atoms_before,
                "rows_after": minimized.atoms_after,
                "changed_atoms": minimized.changed_atoms,
            },
            headline=(
                f"Program and reference diverge after a "
                f"{world.path[-1].family if world.path else 'baseline'} mutation"
            ),
        )

    def fidelity(self, pair: Pair) -> FidelityRecord:
        versions = pair.program.versions or pair.gold.versions
        engine = " ".join(f"{k} {v}" for k, v in versions.items()) or "python"
        return FidelityRecord(found_on="NATIVE_ISOLATED", verified_on=None, engine=engine)

    def data_files(self, state: State) -> dict[str, str]:
        import tempfile

        from isitright.packs.data.mapping import write_state

        with tempfile.TemporaryDirectory(prefix="isitright-out-") as scratch:
            write_state(state, self.prepared.spec.schema, Path(scratch))
            return {f.name: f.read_text(encoding="utf-8") for f in sorted(Path(scratch).iterdir())}

    def replay_artifact(
        self, program: RecordedProgram, case_id: str, world: World, detail: dict[str, Any]
    ) -> ReplayArtifact:
        return ReplayArtifact(
            pack=PACK,
            case_id=case_id,
            world=world.to_json(),
            host={"fidelity": "NATIVE_ISOLATED", "mode": "frozen"},
            inputs={
                "task_id": self.task.id,
                "program_id": program.program_id,
                "program_code": program.code,
                "gold_code": self.task.gold,
                "program_sha256": sha256_text(program.code),
                "files": {f.table: f.file for f in self.task.files},
                "schema": self.prepared.spec.schema.model_dump(mode="json"),
                "policy": self.comparator.describe(),
                "question": self.task.question,
            },
            expected={
                "differs": True,
                "gold_answer": detail.get("gold_answer"),
                "program_answer": detail.get("program_answer"),
            },
        )

    def _report(
        self,
        program: RecordedProgram,
        started: float,
        status: DivergenceStatus,
        result: SearchResult | None,
        headline: str,
        *,
        findings: list[Finding] | None = None,
        errors: list[dict[str, str]] | None = None,
        flags: list[str] | None = None,
        base_pair: Pair | None = None,
        hints: Hints | None = None,
    ) -> CaseReport:
        task, config = self.task, self.config
        found = findings or []
        search_record = (
            SearchRecord(**result.accounting())
            if result is not None
            else SearchRecord(seed=config.seed, attempts=0, valid_candidates=0, executed=0)
        )
        base_validity = self.prepared.spec.validate(self.prepared.base)
        versions = (base_pair.program.versions if base_pair else {}) or {}
        recorded = program.source.library_versions
        notes = [
            f"{name}: recorded on {recorded[name]}, replayed on {versions[name]}"
            for name in sorted(set(recorded) & set(versions))
            if recorded[name] != versions[name]
        ]
        return CaseReport(
            case_id=f"{task.id}:{program.program_id}",
            pack=PACK,
            task=task.question or task.id,
            subject_kind=SubjectKind.FROZEN_ARTIFACT.value,
            divergence_status=status,
            validity=(
                found[0].validity
                if found
                else validity_record(base_validity)
                if result is not None
                else ValidityRecord(status="NOT_ASSESSED")
            ),
            execution_fidelity=(
                found[0].fidelity
                if found
                else FidelityRecord(
                    found_on="NATIVE_ISOLATED",
                    engine=" ".join(f"{k} {v}" for k, v in versions.items()) or None,
                )
            ),
            oracles=[
                OracleRecord(
                    name="gold program",
                    kind="REFERENCE_PROGRAM",
                    outcome="NOT_MET"
                    if found
                    else ("MET" if result is not None and not found else None),
                    description="a reference program run on the same world with the same host",
                    limits=GOLD_LIMITS,
                )
            ],
            search=search_record,
            findings=found,
            comparison_policy=self.comparator.describe(),
            inputs={
                "task_id": task.id,
                "program_id": program.program_id,
                "program_sha256": program.digest,
                "program_source": program.source.model_dump(mode="json"),
                "files": {f.table: f.file for f in task.files},
            },
            original_state={
                "gold_answer": base_pair.gold.answer()[0] if base_pair else None,
                "program_answer": base_pair.program.answer()[0] if base_pair else None,
                "rows": {t: len(f) for t, f in self.prepared.frames.items()},
            },
            assumptions=[
                "The program is run in a separate process with the Python and library versions "
                "named under execution fidelity; a frozen finding is scoped to the program.",
                "Generated worlds are validated against the schema and the declared rules; domain "
                "validation means the supplied rules held, not that the world is plausible.",
                *notes,
            ],
            checked_rules=sorted(
                set(self.prepared.spec.validate(self.prepared.base).checked_rules)
            ),
            unused_rules=[r.name for r in self.prepared.spec.python_constraints],
            errors=errors or [],
            headline=headline,
            elapsed_seconds=time.monotonic() - started,
            extensions={
                PACK: {
                    "mode": "frozen",
                    "host": self.host.describe(),
                    "program_flags": flags or [],
                    "library_versions": versions,
                    "recorded_library_versions": recorded,
                    "program_source_kind": program.source.kind,
                    "hints": hints.to_json() if hints is not None else [],
                    "row_key": ROW_KEY,
                }
            },
        )
