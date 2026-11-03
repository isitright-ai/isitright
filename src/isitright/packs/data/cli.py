"""``isitright data``: audit recorded data-analysis programs and the agents that wrote them."""

from __future__ import annotations

import json
import time
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
    reuse: Annotated[
        int,
        typer.Option(
            min=1,
            help="Runs per host process (1: new process each; more is faster, less isolated).",
        ),
    ] = 1,
) -> None:
    """Frozen audit: replay recorded programs on generated worlds; compare with the gold."""
    _load_audit_deps()
    from isitright.packs.data.audit import AuditConfig, AuditInputError, DataAudit
    from isitright.packs.data.programs import load_programs
    from isitright.packs.data.reports import build_report, write_report
    from isitright.packs.data.task import TaskError, load_task

    if not trust_code:
        typer.echo("This runs recorded programs: pass --trust-code (see --help).", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    if output.exists():
        typer.echo("The output directory already exists; choose a new one.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    started = time.monotonic()
    try:
        recorded = load_programs(programs)
        by_task: dict[str, list[Any]] = {}
        for program in recorded:
            by_task.setdefault(program.task_id, []).append(program)
        cases = []
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
        )
        for directory in _tasks(tasks):
            task = load_task(directory)
            if only and task.id not in only:
                continue
            todo = by_task.get(task.id, [])
            if not todo:
                continue
            try:
                audit = DataAudit(task, config)
            except AuditInputError as error:
                for program in todo:
                    cases.append(_unsupported(task.id, program, str(error)))
                continue
            with audit:
                for program in todo:
                    cases.append(audit.check_frozen(program))
                    typer.echo(f"{cases[-1].case_id}: {cases[-1].divergence_status.value}")
                artifacts.update(audit.artifacts)
    except (TaskError, ValueError, OSError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    report = build_report(cases, time.monotonic() - started)
    write_report(report, output, artifacts)
    found = sum(c.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND for c in cases)
    typer.echo(
        f"{len(cases)} program(s) checked, {found} with a minimized disagreement. Report: {output}"
    )


def _unsupported(task_id: str, program: Any, reason: str) -> Any:
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
        errors=[{"code": "UNSUPPORTED_DATA", "message": reason, "phase": "input"}],
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
