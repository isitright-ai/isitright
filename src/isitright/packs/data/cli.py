"""``isitright data``: audit recorded data-analysis programs and the agents that wrote them."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import typer

from isitright.core.evidence import AuditReport, DivergenceStatus

data_app = typer.Typer(
    help="Audit data-analysis agents: recorded programs (frozen) and agents (live)."
)

EXIT_INTERNAL_ERROR = 1
EXIT_INVALID_INPUT = 2
TRUST_HELP = (
    "Run the recorded programs and the gold program on this machine. They are untrusted code: "
    "they run in a separate, limited process, which is not a security boundary. Use a container."
)


def _tasks(path: Path) -> list[Path]:
    if (path / "task.yaml").is_file():
        return [path]
    return sorted(p for p in path.iterdir() if (p / "task.yaml").is_file())


def _load_audit_deps() -> Any:
    try:
        import pandas  # noqa: F401
    except ImportError as error:
        typer.echo("The data pack needs pandas: pip install 'isitright[data]'", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error


@data_app.command("check")
def check_command(
    tasks: Annotated[
        Path, typer.Argument(exists=True, help="A task directory, or a directory of them.")
    ],
    programs: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="JSONL of recorded programs.")
    ],
    output: Annotated[Path, typer.Option(help="Directory for the report.")],
    trust_code: Annotated[bool, typer.Option("--trust-code", help=TRUST_HELP)] = False,
    attempts: Annotated[int, typer.Option(min=1, help="Worlds to try per program.")] = 300,
    seed: Annotated[int, typer.Option()] = 0,
    depth: Annotated[int, typer.Option(min=1, max=3)] = 2,
    findings: Annotated[int, typer.Option(min=1, help="Findings to keep per program.")] = 1,
    timeout: Annotated[float, typer.Option(min=0.1, help="Seconds per program run.")] = 30.0,
    memory_mb: Annotated[int, typer.Option(min=64, help="Memory limit per run (MiB).")] = 2048,
    only: Annotated[list[str], typer.Option(help="Audit only these task ids.")] = [],  # noqa: B006
    serial: Annotated[
        bool, typer.Option(help="Run the gold and the program one at a time (less memory).")
    ] = False,
    reuse: Annotated[
        int,
        typer.Option(
            min=1,
            help="Runs per host process (1: new process each; more is faster, less isolated).",
        ),
    ] = 1,
    cache: Annotated[
        Path | None,
        typer.Option(
            help="Directory that keeps finished runs, so an interrupted audit can resume without "
            "repeating them. Files are removed once a program's result is saved."
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            help="Continue an interrupted audit in an existing --output directory: programs "
            "that finished are kept, the rest start again (from --cache when it was used). "
            "The settings must match the interrupted run."
        ),
    ] = False,
) -> None:
    """Frozen audit: replay recorded programs on generated worlds; compare with the gold."""
    _load_audit_deps()
    from isitright.packs.data.audit import AuditConfig
    from isitright.packs.data.programs import load_programs
    from isitright.packs.data.reports import build_report, write_report
    from isitright.packs.data.task import TaskError, load_task

    if not trust_code:
        typer.echo("This runs recorded programs: pass --trust-code (see --help).", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    if output.exists() and not resume:
        typer.echo(
            "The output directory already exists; choose a new one (or --resume an "
            "interrupted audit).",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID_INPUT)
    if (output / "report.json").exists():
        typer.echo(f"The audit in {output} has finished; there is nothing to resume.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    started = time.monotonic()
    try:
        recorded = load_programs(programs)
        by_task: dict[str, list[Any]] = {}
        for program in recorded:
            by_task.setdefault(program.task_id, []).append(program)
        cases: list[Any] = []
        artifacts: dict[str, Any] = {}
        config = AuditConfig(
            seed=seed,
            attempts=attempts,
            depth=depth,
            findings=findings,
            timeout_seconds=timeout,
            memory_mb=memory_mb,
            trust_code=True,
            reuse=reuse,
            parallel=not serial,
            cache_dir=cache,
        )
        state = _start_state(
            output,
            {
                "seed": seed,
                "attempts": attempts,
                "depth": depth,
                "findings": findings,
                "timeout": timeout,
                "memory_mb": memory_mb,
                "reuse": reuse,
                "programs": _digest(programs),
            },
        )
        for directory in _tasks(tasks):
            task = load_task(directory)
            if only and task.id not in only:
                continue
            todo = by_task.get(task.id, [])
            if todo:
                task_cases, task_artifacts = _check_task(task, todo, config, state)
                cases.extend(task_cases)
                artifacts.update(task_artifacts)
    except (TaskError, ValueError, OSError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    report = build_report(cases, time.monotonic() - started)
    write_report(report, output, artifacts)
    shutil.rmtree(state, ignore_errors=True)
    if cache is not None:
        with suppress(OSError):
            cache.rmdir()
    found = sum(c.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND for c in cases)
    typer.echo(
        f"{len(cases)} program(s) checked, {found} with a minimized disagreement. Report: {output}"
    )


RESUME_DIR = ".resume"
RETRY_CODES = {"INTERNAL_ERROR", "BASELINE_RUN"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _start_state(output: Path, settings: dict[str, Any]) -> Path:
    """The directory that holds finished programs; a resumed run must use the same settings."""
    state = output / RESUME_DIR
    marker = state / "run.json"
    if marker.is_file():
        earlier = json.loads(marker.read_text(encoding="utf-8"))
        changed = sorted(
            k for k in settings.keys() | earlier.keys() if earlier.get(k) != settings.get(k)
        )
        if changed:
            typer.echo(
                "--resume needs the settings of the interrupted run; different: "
                + ", ".join(changed),
                err=True,
            )
            raise typer.Exit(EXIT_INVALID_INPUT)
    (state / "units").mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(settings, sort_keys=True), encoding="utf-8")
    return state


def _unit(state: Path, case_id: str) -> Path:
    from isitright.packs.data.reports import safe_id

    return state / "units" / f"{safe_id(case_id)}.json"


def _save_unit(state: Path, case: Any, artifacts: dict[str, Any]) -> None:
    """Keep a finished program's result (written whole, so a crash never leaves half of one)."""
    if any(e.get("code") in RETRY_CODES for e in case.errors):
        return  # an environment problem: a resumed run tries the program again
    mine = {
        k: v.model_dump(mode="json")
        for k, v in artifacts.items()
        if k.startswith(case.case_id + ":")
    }
    path = _unit(state, case.case_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"case": case.model_dump(mode="json"), "artifacts": mine}), encoding="utf-8"
    )
    os.replace(temporary, path)


def _load_unit(state: Path, case_id: str) -> tuple[Any, dict[str, Any]] | None:
    from isitright.core.evidence import CaseReport
    from isitright.core.replay import ReplayArtifact

    try:
        payload = json.loads(_unit(state, case_id).read_text(encoding="utf-8"))
        return (
            CaseReport.model_validate(payload["case"]),
            {k: ReplayArtifact.model_validate(v) for k, v in payload["artifacts"].items()},
        )
    except (OSError, ValueError, KeyError):
        return None


def _check_task(
    task: Any, todo: list[Any], config: Any, state: Path
) -> tuple[list[Any], dict[str, Any]]:
    """The cases of one task, in program order: finished ones come from ``state``."""
    from isitright.packs.data.audit import AuditInputError, DataAudit
    from isitright.packs.data.host import UntrustedCodeError

    cases: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    for program in todo:
        unit = _load_unit(state, f"{task.id}:{program.program_id}")
        if unit is not None:
            cases[program.program_id] = unit[0]
            artifacts.update(unit[1])
            typer.echo(f"{unit[0].case_id}: {unit[0].divergence_status.value} (kept from before)")
    pending = [p for p in todo if p.program_id not in cases]
    if pending:
        try:
            audit = DataAudit(task, config)
        except AuditInputError as error:
            for program in pending:
                cases[program.program_id] = _unsupported(task.id, program, str(error))
        else:
            with audit:
                for program in pending:
                    try:
                        case = audit.check_frozen(program)
                    except UntrustedCodeError:
                        raise
                    except Exception as error:  # one program must not end the whole audit
                        case = _unsupported(
                            task.id, program, f"{type(error).__name__}: {error}", "INTERNAL_ERROR"
                        )
                    cases[program.program_id] = case
                    _save_unit(state, case, audit.artifacts)
                    audit.discard_cache(program)
                    typer.echo(f"{case.case_id}: {case.divergence_status.value}")
                artifacts.update(audit.artifacts)
                audit.discard_cache()
    return [cases[p.program_id] for p in todo], artifacts


def _unsupported(task_id: str, program: Any, reason: str, code: str = "UNSUPPORTED_DATA") -> Any:
    from isitright.core.evidence import CaseReport, FidelityRecord, SearchRecord, ValidityRecord

    return CaseReport(
        case_id=f"{task_id}:{program.program_id}",
        pack="data",
        subject_kind="FROZEN_ARTIFACT",
        divergence_status=DivergenceStatus.UNSUPPORTED,
        validity=ValidityRecord(status="NOT_ASSESSED"),
        execution_fidelity=FidelityRecord(found_on="NATIVE_ISOLATED"),
        oracles=[],
        search=SearchRecord(seed=0, attempts=0, valid_candidates=0, executed=0),
        errors=[{"code": code, "message": reason, "phase": "input"}],
        headline=f"Unsupported: {reason[:200]}",
        elapsed_seconds=0.0,
    )


@data_app.command("audit")
def audit_command(
    task: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="A task directory.")],
    agent: Annotated[str, typer.Option(help="Agent factory, module:callable (see docs/data.md).")],
    output: Annotated[Path, typer.Option(help="Directory for the report.")],
    programs: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="The agent's recorded baseline program (screens worlds).",
        ),
    ] = None,
    trust_code: Annotated[bool, typer.Option("--trust-code", help=TRUST_HELP)] = False,
    pass_env: Annotated[
        list[str], typer.Option(help="Environment variable names to pass to the agent (API keys).")
    ] = [],  # noqa: B006
    agent_kwargs: Annotated[
        str, typer.Option(help="JSON keyword arguments for the factory.")
    ] = "{}",
    baseline_runs: Annotated[int, typer.Option(min=1)] = 3,
    max_trials: Annotated[int, typer.Option(min=1)] = 10,
    max_worlds: Annotated[int, typer.Option(min=1, help="Safety rail on worlds run live.")] = 40,
    attempts: Annotated[int, typer.Option(min=1)] = 300,
    ranking: Annotated[
        str, typer.Option(help="diverse, screening, coverage or random.")
    ] = "diverse",
    stratum_patience: Annotated[int, typer.Option(min=0)] = 10,
    run_patience: Annotated[int, typer.Option(min=0)] = 30,
    max_runs: Annotated[int | None, typer.Option(min=1, help="Budget: agent runs.")] = None,
    max_money: Annotated[
        float | None, typer.Option(min=0.0, help="Budget: money, as the agent reports it.")
    ] = None,
    max_seconds: Annotated[float | None, typer.Option(min=1.0)] = None,
    seed: Annotated[int, typer.Option()] = 0,
    agent_timeout: Annotated[float, typer.Option(min=1.0)] = 600.0,
) -> None:
    """Live audit: confirm frozen candidates with the agent itself (costly; needs --trust-code)."""
    _load_audit_deps()
    from isitright.core.stochastic import Budget
    from isitright.packs.data.adapters import SubprocessAgent
    from isitright.packs.data.audit import AuditConfig, DataAudit
    from isitright.packs.data.live import LiveConfig, run_live
    from isitright.packs.data.programs import load_programs
    from isitright.packs.data.reports import build_report, write_report
    from isitright.packs.data.task import load_task

    if not trust_code:
        typer.echo("This runs an agent and its code: pass --trust-code (see --help).", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    if max_money is not None:
        typer.echo(
            "A money budget needs the agent to report its cost; runs that report none are refused.",
            err=True,
        )
    if output.exists():
        typer.echo("The output directory already exists; choose a new one.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    started = time.monotonic()
    loaded = load_task(task)
    program = None
    if programs is not None:
        matching = [p for p in load_programs(programs) if p.task_id == loaded.id]
        program = matching[0] if matching else None
    runner = SubprocessAgent(
        agent,
        trust_code=True,
        pass_env=tuple(pass_env),
        timeout_seconds=agent_timeout,
        kwargs=json.loads(agent_kwargs),
        name=agent,
    )
    config = LiveConfig(
        baseline_runs=baseline_runs,
        max_trials=max_trials,
        attempts=attempts,
        seed=seed,
        ranking=ranking,  # type: ignore[arg-type]
        stratum_patience=stratum_patience or None,
        run_patience=run_patience or None,
        max_worlds=max_worlds,
    )
    with DataAudit(loaded, AuditConfig(trust_code=True, seed=seed)) as audit:
        frozen_finding = frozen_world = None
        if program is not None:
            frozen = audit.check_frozen(program)
            if frozen.findings:
                frozen_finding = frozen.findings[0]
                from isitright.core.mutations import World

                frozen_world = World.from_json(audit.artifacts[frozen_finding.finding_id].world)
        case = run_live(
            audit,
            runner,
            program=program,
            config=config,
            frozen_finding=frozen_finding,
            frozen_world=frozen_world,
            budget=Budget(runs=max_runs, money=max_money, seconds=max_seconds),
            progress=lambda _world, marker: typer.echo(marker, nl=False),
        )
    typer.echo("")
    write_report(build_report([case], time.monotonic() - started, kind="case"), output, {})
    typer.echo(case.headline)


@data_app.command("replay")
def replay_command(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    trust_code: Annotated[bool, typer.Option("--trust-code", help=TRUST_HELP)] = False,
    finding: Annotated[int, typer.Option(min=1, help="Which finding of the report (1-based).")] = 1,
) -> None:
    """Replay a finding of a report from its recorded world."""
    _load_audit_deps()
    from isitright.packs.data.reports import load_and_replay

    if not trust_code:
        typer.echo("This reruns recorded programs: pass --trust-code (see --help).", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    audit = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
    findings = [f for c in audit.cases for f in c.findings if f.replay.artifact]
    if finding > len(findings):
        typer.echo("The report has no such finding with a replay artifact.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    artifact = report.parent / str(findings[finding - 1].replay.artifact)
    result = load_and_replay(artifact, trust_code=True)
    typer.echo(
        "Reproduced both answers and the disagreement."
        if result.reproduced
        else "Did not reproduce:"
    )
    for line in result.details:
        typer.echo(f"  {line}")
    if not result.reproduced:
        raise typer.Exit(EXIT_INTERNAL_ERROR)


@data_app.command("export")
def export_command(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Directory for the eval cases.")],
) -> None:
    """Export findings as eval cases: dataset (CSV), question, gold program, expected answer."""
    from isitright.packs.data.reports import export_eval_cases

    audit = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
    cases = export_eval_cases(audit, output)
    index = output / "cases.jsonl"
    index.write_text(
        "".join(
            json.dumps(c.model_dump(mode="json"), sort_keys=True, default=str) + "\n" for c in cases
        ),
        encoding="utf-8",
    )
    typer.echo(f"Exported {len(cases)} eval case(s) to {output}")
