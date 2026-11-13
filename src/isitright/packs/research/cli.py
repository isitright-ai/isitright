"""``isitright research``: audit research agents that answer from a frozen corpus.

``check`` runs a subject (a stand-in agent, an agent given as code, an agent command, or a recorded
run replayed frozen) on mutated corpora; ``replay`` reproduces a finding offline from its artifact;
``export`` writes a finding as a new eval case. No command here calls a model: a subject that is a
real agent is one the user runs, with their own credentials, through ``--agent-command``.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Annotated, Any

import typer

from isitright.core.evidence import FailOn, policy_triggered

research_app = typer.Typer(
    help="Audit research agents: documents planted, removed, superseded or retracted in a corpus."
)

EXIT_INTERNAL_ERROR = 1
EXIT_INVALID_INPUT = 2
EXIT_POLICY_TRIGGERED = 3
TRUST_HELP = (
    "Run the agent (code or command) on this machine. It is trusted code: it is not sandboxed, "
    "and an agent command may reach the network and use credentials. Use a container."
)


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(EXIT_INVALID_INPUT)


@research_app.command("check")
def check_command(
    corpus: Annotated[
        Path,
        typer.Argument(exists=True, help="A corpus.jsonl file, or a directory of documents."),
    ],
    task: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="The task as JSON (see the docs).")
    ],
    output: Annotated[Path, typer.Option(help="Directory for the report and artifacts.")],
    stand_in: Annotated[
        str | None,
        typer.Option(
            help="A built-in stand-in agent written by Claude: careful, credulous, "
            "snippet_reader, non_retrieving, refusing or mixed. Not a real agent."
        ),
    ] = None,
    agent: Annotated[
        str | None, typer.Option(help="An agent as code: module:attr or file.py:attr.")
    ] = None,
    agent_command: Annotated[
        str | None,
        typer.Option(
            help="An agent command that uses an MCP server. {mcp_config}, {task_file} and "
            "{run_dir} are substituted; it writes report.json into {run_dir}."
        ),
    ] = None,
    recorded_run: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="A recorded run, replayed frozen: the report is not regenerated.",
        ),
    ] = None,
    trust_code: Annotated[bool, typer.Option("--trust-code", help=TRUST_HELP)] = False,
    hints: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="Declared hints as JSON (a list)."),
    ] = None,
    attempts: Annotated[int, typer.Option(min=1, help="Worlds to try.")] = 500,
    seed: Annotated[int, typer.Option()] = 0,
    depth: Annotated[int, typer.Option(min=1, max=3)] = 2,
    retriever: Annotated[
        str,
        typer.Option(
            help="The retriever behind the tools: bm25, hashed-dense or hybrid. The last two "
            "are stand-ins for a dense retriever (a hashed bag-of-words embedding), not a model."
        ),
    ] = "bm25",
    runs: Annotated[
        int | None,
        typer.Option(min=1, help="Runs per world (default 1; 4 for a stochastic agent)."),
    ] = None,
    max_runs: Annotated[int | None, typer.Option(min=1, help="Budget in agent runs.")] = None,
    seconds: Annotated[float | None, typer.Option(min=1, help="Budget in wall time.")] = None,
    max_money: Annotated[
        float | None,
        typer.Option(min=0, help="Budget in money; refused for an agent that reports no cost."),
    ] = None,
    timeout: Annotated[float, typer.Option(min=1, help="Seconds per agent-command run.")] = 600.0,
    screen: Annotated[
        bool,
        typer.Option(
            help="Replay the baseline trace on each world first and run the agent only where the "
            "replay shows a change it could see."
        ),
    ] = False,
    minimize: Annotated[bool, typer.Option(help="Minimize the corpus of each finding.")] = True,
    allow_failing_baseline: Annotated[
        bool,
        typer.Option(
            help="Audit although the baseline abstains or does not match the gold answer."
        ),
    ] = False,
    record_runs: Annotated[
        Path | None, typer.Option(help="Write each baseline run here as a recorded run.")
    ] = None,
    fail_on: Annotated[FailOn, typer.Option()] = FailOn.NONE,
) -> None:
    """Audit a research agent on mutated corpora."""
    from isitright.core.hints import hints_from_json
    from isitright.packs.research.agents import STAND_INS, ResearchTask
    from isitright.packs.research.audit import AuditConfig, ResearchAudit, ResearchInputError
    from isitright.packs.research.documents import CorpusError, load_corpus
    from isitright.packs.research.external import ExternalError, command_subject, load_agent
    from isitright.packs.research.replaying import write_outputs
    from isitright.packs.research.runs import read_run, write_run

    chosen = [x for x in (stand_in, agent, agent_command, recorded_run) if x is not None]
    if len(chosen) != 1:
        raise _fail("Choose exactly one of --stand-in, --agent, --agent-command, --recorded-run.")
    if (agent or agent_command) and not trust_code:
        raise _fail("This runs an agent: pass --trust-code (see --help).")
    if output.exists():
        raise _fail("The output directory already exists; choose a new one.")
    try:
        research_task = ResearchTask.model_validate_json(task.read_text(encoding="utf-8"))
        declared = hints_from_json(json.loads(hints.read_text(encoding="utf-8"))) if hints else []
        state = load_corpus(corpus, cutoff=research_task.cutoff)
        config = AuditConfig(
            seed=seed,
            attempts=attempts,
            depth=depth,
            retriever=retriever,
            runs=runs,
            max_runs=max_runs,
            seconds=seconds,
            money=max_money,
            screen=screen,
            minimize=minimize,
            allow_failing_baseline=allow_failing_baseline,
            declared_hints=declared,
        )
        audit = ResearchAudit(state, research_task, config)
        if recorded_run is not None:
            case = audit.check_frozen(read_run(recorded_run))
        else:
            if stand_in is not None:
                if stand_in not in STAND_INS:
                    raise ExternalError(f"unknown stand-in {stand_in!r}: {', '.join(STAND_INS)}")
                subject = audit.stand_in(STAND_INS[stand_in](research_task))
            elif agent is not None:
                subject = audit.stand_in(load_agent(agent, research_task))
            else:
                assert agent_command is not None
                subject = command_subject(
                    _split(agent_command), research_task, audit.stats, timeout=timeout
                )
            case = audit.check(subject)
    except (ExternalError, CorpusError, ResearchInputError, ValueError, OSError) as error:
        raise _fail(f"Input error: {error}") from error
    written = write_outputs(output, case, audit.artifacts, audit.exports, audit.cannot_judge_rows)
    if record_runs is not None:
        record_runs.mkdir(parents=True, exist_ok=True)
        for i, run in enumerate(audit.baseline_runs, start=1):
            write_run(record_runs / f"baseline-{i}.json", run)
    typer.echo(case.headline)
    for path in written:
        typer.echo(f"Wrote {path}")
    if policy_triggered(case, fail_on):
        raise typer.Exit(EXIT_POLICY_TRIGGERED)


def _split(command: str) -> list[str]:
    from isitright.packs.mcp.runner import split_command

    return split_command(command) if command.strip() else shlex.split(command)


@research_app.command("replay")
def replay_command(
    artifact: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Reproduce a finding offline from its replay artifact."""
    from isitright.packs.research.replaying import replay_file

    try:
        result = replay_file(artifact)
    except (ValueError, KeyError, OSError) as error:
        raise _fail(f"Input error: {error}") from error
    for line in result.details:
        typer.echo(line)
    typer.echo("Reproduced." if result.reproduced else "Not reproduced.")
    if not result.reproduced:
        raise typer.Exit(EXIT_INTERNAL_ERROR)


@research_app.command("export")
def export_command(
    report: Annotated[
        Path, typer.Argument(exists=True, help="A report.json written by `research check`.")
    ],
    output: Annotated[Path, typer.Option(help="Directory for the eval cases.")],
) -> None:
    """Write each finding of a report as a new eval case (corpus, question, expectation)."""
    from isitright.core.replay import load_artifact
    from isitright.packs.research.replaying import export_case, load_report

    try:
        loaded = load_report(report)
    except (ValueError, OSError) as error:
        raise _fail(f"Input error: {error}") from error
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for case in loaded.cases:
        for finding in case.findings:
            if not finding.replay.artifact:
                continue
            path = report.parent / finding.replay.artifact
            data: dict[str, Any] = export_case(load_artifact(path))
            target = output / f"{finding.finding_id.rsplit(':', 1)[1]}.eval-case.json"
            target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
            typer.echo(f"Wrote {target}")
            count += 1
    typer.echo(f"{count} eval case(s) exported.")
