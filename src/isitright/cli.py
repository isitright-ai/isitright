"""Command-line interface for isitright."""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from isitright import __version__
from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    DivergenceStatus,
    FailOn,
    policy_triggered,
)
from isitright.packs.sql import (
    CheckConfig,
    InputError,
    SqlInputError,
    check,
    check_suite,
    export_eval_cases,
    replay_report,
)
from isitright.packs.sql.constraints_file import ConstraintInputError
from isitright.packs.sql.models import (
    ColumnComparisonPolicy,
    FloatComparisonMode,
    OrderingPolicy,
)
from isitright.packs.sql.reports import ReportFormat, write_case_report, write_suite_report
from isitright.packs.sql.slicing import (
    DEFAULT_CAP as DEFAULT_SLICE_CAP,
)
from isitright.packs.sql.slicing import (
    DEFAULT_PAD as DEFAULT_SLICE_PAD,
)
from isitright.packs.sql.slicing import (
    SliceError,
    slice_database,
)
from isitright.packs.sql.suite import SuiteInputError

EXIT_INTERNAL_ERROR = 1
EXIT_INVALID_INPUT = 2
EXIT_POLICY_TRIGGERED = 3

ORDERING_HELP = (
    "Result-order policy. auto requires order only when the reference query has a "
    "top-level ORDER BY; ordered always requires order; unordered always ignores order."
)

app = typer.Typer(
    name="isitright",
    help="Audit agent evals: find valid changes to the world under which a pass no longer holds.",
    no_args_is_help=True,
)
sql_app = typer.Typer(help="Audit text-to-SQL programs (SQLite, PostgreSQL, DuckDB).")
app.add_typer(sql_app, name="sql")
agents_app = typer.Typer(help="Audit tool-using agents against perturbed worlds over MCP.")
app.add_typer(agents_app, name="agents")
hints_app = typer.Typer(help="Propose hints with a model, then confirm them (labeled proposed).")
agents_app.add_typer(hints_app, name="hints")


class Engine(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    DUCKDB = "duckdb"


class AgentsFailOn(StrEnum):
    NONE = "none"
    INVARIANT = "invariant-violation"
    ANY_FINDING = "any-finding"


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"isitright {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Audit agent evals with world perturbation, validity checks and replayable evidence."""
    del version


class _CandidateProgress:
    """Print candidate outcomes as they occur, without changing report contents."""

    def __init__(self) -> None:
        self.current_case: str | None = None

    def update(self, case_id: str, outcome: str) -> None:
        if self.current_case != case_id:
            self.finish()
            self.current_case = case_id
            typer.echo(f"{case_id}: ", nl=False)
        typer.echo(
            {"agreement": ".", "counterexample": "C", "rejected": "x", "error": "?"}[outcome],
            nl=False,
        )

    def finish(self) -> None:
        if self.current_case is not None:
            typer.echo()
            self.current_case = None


class _RunProgress:
    """Print one marker per agent run, a line per world, and count the runs (on stderr)."""

    LEGEND = (
        ". as expected  V invariant violated  N expected behavior not met  "
        "? not judged  E run did not complete"
    )

    def __init__(self) -> None:
        self.current_world: str | None = None
        self.runs = 0
        self.started = time.monotonic()

    def update(self, world_id: str, marker: str) -> None:
        if self.current_world != world_id:
            self.finish()
            self.current_world = world_id
            typer.echo(f"{world_id}: ", nl=False, err=True)
        self.runs += 1
        typer.echo(marker, nl=False, err=True)

    def finish(self) -> None:
        if self.current_world is not None:
            typer.echo(err=True)
            self.current_world = None

    def elapsed(self) -> str:
        minutes, seconds = divmod(int(time.monotonic() - self.started), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m {seconds:02d}s"
        return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def _config(
    seed: int,
    max_attempts: int,
    minimization_attempts: int,
    timeout: float,
    max_result_rows: int,
    column_policy: ColumnComparisonPolicy,
    ordering: OrderingPolicy,
    float_mode: FloatComparisonMode,
    float_rtol: float,
    float_atol: float,
) -> CheckConfig:
    return CheckConfig(
        seed=seed,
        max_attempts=max_attempts,
        minimization_max_attempts=minimization_attempts,
        timeout_seconds=timeout,
        max_result_rows=max_result_rows,
        column_policy=column_policy,
        ordering_policy=ordering,
        float_mode=float_mode,
        float_relative_tolerance=float_rtol,
        float_absolute_tolerance=float_atol,
    )


def _source(engine: Engine, database: Path | None, schema: Path | None) -> dict[str, Any]:
    if engine is Engine.SQLITE:
        if (database is None) == (schema is None):
            raise typer.BadParameter("sqlite needs exactly one of --database and --schema")
        return {"database": database} if database else {"ddl": schema.read_text(encoding="utf-8")}  # type: ignore[union-attr]
    if schema is None or database is not None:
        raise typer.BadParameter(f"{engine.value} needs --schema (DDL) and no --database")
    return {"ddl": schema.read_text(encoding="utf-8")}


_INPUT_ERRORS = (InputError, SqlInputError, ConstraintInputError, SuiteInputError, OSError)


@sql_app.command("check")
def check_command(
    reference_sql: Annotated[Path, typer.Option("--reference", exists=True, dir_okay=False)],
    candidate_sql: Annotated[Path, typer.Option("--candidate", exists=True, dir_okay=False)],
    engine: Annotated[
        Engine, typer.Option(help="sqlite, postgres (native) or duckdb (emulated).")
    ] = (Engine.SQLITE),
    database: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, readable=True, help="SQLite file.")
    ] = None,
    schema: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, readable=True, help="DDL file.")
    ] = None,
    constraints: Annotated[
        Path | None, typer.Option("--constraints", exists=True, dir_okay=False)
    ] = None,
    seed: Annotated[int, typer.Option()] = 0,
    max_attempts: Annotated[int, typer.Option(min=1)] = 500,
    minimization_attempts: Annotated[int, typer.Option(min=0)] = 500,
    timeout: Annotated[float, typer.Option(min=0.001)] = 30.0,
    max_result_rows: Annotated[int, typer.Option(min=1)] = 10_000,
    column_policy: Annotated[ColumnComparisonPolicy, typer.Option()] = (
        ColumnComparisonPolicy.POSITIONAL
    ),
    ordering: Annotated[OrderingPolicy, typer.Option(help=ORDERING_HELP)] = OrderingPolicy.AUTO,
    float_mode: Annotated[FloatComparisonMode, typer.Option()] = FloatComparisonMode.ISCLOSE,
    float_rtol: Annotated[float, typer.Option(min=0)] = 1e-9,
    float_atol: Annotated[float, typer.Option(min=0)] = 1e-12,
    output_dir: Annotated[Path, typer.Option()] = Path("artifacts/check"),
    report_format: Annotated[ReportFormat, typer.Option("--format")] = ReportFormat.BOTH,
    fail_on: Annotated[FailOn, typer.Option()] = FailOn.NONE,
    verify_native: Annotated[
        bool,
        typer.Option(
            help="Re-execute findings from the duckdb engine on PostgreSQL when it is installed."
        ),
    ] = True,
) -> None:
    """Compare one query pair on perturbed worlds of a database or schema."""
    progress = _CandidateProgress()
    try:
        if engine is not Engine.SQLITE and output_dir.exists():
            raise SqlInputError("output directory already exists; choose a new directory")
        source = _source(engine, database, schema)
        typer.echo("Live candidate states: . agreement  C difference  x rejected  ? error")
        result = check(
            reference_sql=reference_sql.read_text(encoding="utf-8"),
            candidate_sql=candidate_sql.read_text(encoding="utf-8"),
            engine=engine.value,
            constraints_file=constraints,
            verify_native=None if verify_native else False,
            config=_config(
                seed,
                max_attempts,
                minimization_attempts,
                timeout,
                max_result_rows,
                column_policy,
                ordering,
                float_mode,
                float_rtol,
                float_atol,
            ),
            _progress=lambda event: progress.update("Candidate states", event),
            **source,
        )
        progress.finish()
        written = write_case_report(result, output_dir, report_format)
    except _INPUT_ERRORS as error:
        progress.finish()
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    except typer.BadParameter:
        raise
    except Exception as error:
        progress.finish()
        typer.echo(f"internal error: {error}", err=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from error

    typer.echo(result.headline)
    if engine is not Engine.SQLITE:
        _print_case_summary(result, output_dir)
    for path in written:
        typer.echo(f"Wrote {path}")
    if result.divergence_status is DivergenceStatus.INCONCLUSIVE and engine is not Engine.SQLITE:
        raise typer.Exit(EXIT_INTERNAL_ERROR)
    if policy_triggered(result, fail_on):
        raise typer.Exit(EXIT_POLICY_TRIGGERED)


@sql_app.command("slice")
def slice_command(
    database: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, readable=True, help="SQLite file.")
    ],
    reference_sql: Annotated[Path, typer.Option("--reference", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="The slice to write (a new SQLite file).")],
    cap: Annotated[
        int, typer.Option(min=1, help="Joined tuples of the reference query to keep.")
    ] = DEFAULT_SLICE_CAP,
    pad: Annotated[
        int, typer.Option(min=0, help="Rows kept of each table only a subquery names.")
    ] = DEFAULT_SLICE_PAD,
) -> None:
    """Cut a small database from a large one: the rows the reference query used.

    Use the result as --database of `sql check`. The audit then covers worlds near the slice, not
    the original database, and says so only if you do: keep the slice with the report.
    """
    try:
        result = slice_database(
            database, reference_sql.read_text(encoding="utf-8"), output, cap=cap, pad=pad
        )
    except (SliceError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo(f"Wrote {result.path}: {result.rows} rows, {result.tuples} joined tuples.")


@sql_app.command("suite")
def suite_command(
    cases: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    engine: Annotated[
        Engine, typer.Option(help="sqlite, postgres (native) or duckdb (emulated).")
    ] = (Engine.SQLITE),
    database: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, readable=True, help="SQLite file.")
    ] = None,
    schema: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, readable=True, help="DDL file.")
    ] = None,
    constraints: Annotated[
        Path | None, typer.Option("--constraints", exists=True, dir_okay=False)
    ] = None,
    seed: Annotated[int, typer.Option()] = 0,
    max_attempts: Annotated[int, typer.Option(min=1)] = 500,
    minimization_attempts: Annotated[int, typer.Option(min=0)] = 500,
    timeout: Annotated[float, typer.Option(min=0.001)] = 30.0,
    max_result_rows: Annotated[int, typer.Option(min=1)] = 10_000,
    column_policy: Annotated[ColumnComparisonPolicy, typer.Option()] = (
        ColumnComparisonPolicy.POSITIONAL
    ),
    ordering: Annotated[OrderingPolicy, typer.Option(help=ORDERING_HELP)] = OrderingPolicy.AUTO,
    float_mode: Annotated[FloatComparisonMode, typer.Option()] = FloatComparisonMode.ISCLOSE,
    float_rtol: Annotated[float, typer.Option(min=0)] = 1e-9,
    float_atol: Annotated[float, typer.Option(min=0)] = 1e-12,
    output_dir: Annotated[Path, typer.Option()] = Path("artifacts/suite"),
    report_format: Annotated[ReportFormat, typer.Option("--format")] = ReportFormat.BOTH,
    fail_on: Annotated[FailOn, typer.Option()] = FailOn.NONE,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show every case and written artifact.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Show only totals and the report directory.")
    ] = False,
    verify_native: Annotated[
        bool,
        typer.Option(
            help="Re-execute findings from the duckdb engine on PostgreSQL when it is installed."
        ),
    ] = True,
) -> None:
    """Analyze a JSONL evaluation suite with per-case isolation and ranking."""
    if verbose and quiet:
        raise typer.BadParameter("--verbose and --quiet cannot be used together")
    progress = _CandidateProgress()
    try:
        if engine is not Engine.SQLITE and output_dir.exists():
            raise SqlInputError("output directory already exists; choose a new directory")
        source = _source(engine, database, schema)
        if not quiet:
            typer.echo("Live candidate states: . agreement  C difference  x rejected  ? error")
        result = check_suite(
            cases=cases,
            engine=engine.value,
            constraints_file=constraints,
            verify_native=None if verify_native else False,
            config=_config(
                seed,
                max_attempts,
                minimization_attempts,
                timeout,
                max_result_rows,
                column_policy,
                ordering,
                float_mode,
                float_rtol,
                float_atol,
            ),
            _progress=progress.update if not quiet else None,
            **source,
        )
        progress.finish()
        written = write_suite_report(result, output_dir, report_format)
    except _INPUT_ERRORS as error:
        progress.finish()
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    except Exception as error:
        progress.finish()
        typer.echo(f"internal error: {error}", err=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from error

    _print_suite_output(
        result, output_dir=output_dir, written=written, verbose=verbose, quiet=quiet
    )
    if engine is Engine.DUCKDB:
        typer.echo("DuckDB is an approximation; findings have not been checked on PostgreSQL.")
    if any(policy_triggered(case, fail_on) for case in result.cases):
        raise typer.Exit(EXIT_POLICY_TRIGGERED)


@sql_app.command("replay")
def replay_command(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    timeout: Annotated[float, typer.Option(min=0.001)] = 30.0,
    max_result_rows: Annotated[int, typer.Option(min=1)] = 10_000,
) -> None:
    """Replay the first counterexample of a case report from its recorded world."""
    try:
        audit = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
        result = replay_report(
            audit.cases[0], timeout_seconds=timeout, max_result_rows=max_result_rows
        )
    except _INPUT_ERRORS as error:
        typer.echo(f"Replay error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    except Exception as error:
        typer.echo(f"Replay error: {error}", err=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from error
    if result["reproduced"]:
        typer.echo(
            f"Reproduced both query outputs on {result['execution_engine']} "
            f"{result['engine_version']}."
        )
    else:
        typer.echo("Replay did not reproduce both recorded outputs.")
    if not result["version_matches"]:
        typer.echo(
            f"Engine version differs from the recorded version {result['recorded_engine_version']}."
        )
    if not result["reproduced"]:
        raise typer.Exit(EXIT_INTERNAL_ERROR)


@sql_app.command("export")
def export_command(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option(help="JSONL file to append eval cases to.")],
) -> None:
    """Export a report's counterexamples as new eval cases (one JSON object per line)."""
    try:
        audit = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
        cases = [c for case in audit.cases if case.findings for c in export_eval_cases(case)]
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")
    except Exception as error:
        typer.echo(f"Export error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo(f"Exported {len(cases)} eval case(s) to {output}")


def _print_case_summary(result: CaseReport, output_dir: Path) -> None:
    """Explain a PostgreSQL or DuckDB check without requiring report-contract knowledge."""
    tested = result.search.executed
    version = (result.execution_fidelity.engine or "").partition(" ")[2]
    suffix = f" {version}" if version else ""
    if result.execution_fidelity.found_on == "EMULATED":
        engine = f"DuckDB{suffix} (emulating PostgreSQL)"
    else:
        engine = f"native PostgreSQL{suffix}"
    typer.echo(
        f"Tested {tested} generated database state{'' if tested == 1 else 's'} using {engine}."
    )
    status = result.divergence_status
    if status is DivergenceStatus.COUNTEREXAMPLE_FOUND and result.findings:
        finding = result.findings[0]
        divergence = finding.divergence
        typer.echo(f"Found a difference on a {divergence['generator']} state:")
        typer.echo(f"  Data: {json.dumps(divergence['candidate_state'], ensure_ascii=False)}")
        for label, key in (("Reference", "reference_result"), ("Candidate", "candidate_result")):
            rows = divergence[key]["rows"]
            values = [[value["value"] for value in row] for row in rows[:5]]
            shown = json.dumps(values, ensure_ascii=False)
            if len(rows) > 5:
                shown += f" (showing 5 of {len(rows)} rows)"
            typer.echo(f"  {label} returned: {shown}")
        tiers = set(result.validity.tiers)
        validity = (
            "supplied domain rules passed"
            if "DOMAIN_VALIDATED" in tiers
            else "domain validity was not checked"
        )
        checker = "DuckDB" if result.execution_fidelity.found_on == "EMULATED" else "PostgreSQL"
        typer.echo(f"{checker} accepted the supported schema; {validity}.")
        if result.execution_fidelity.found_on == "EMULATED":
            typer.echo(
                "DuckDB is an approximation; this difference has not been checked on PostgreSQL."
            )
        typer.echo(f"Reproduction: {output_dir / 'counterexample.sql'}")
    elif status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET:
        typer.echo("No difference found in the states tested; this does not prove equivalence.")
        if result.search.budget.get("stopped_by") == "attempts":
            typer.echo("The search stopped at the configured state limit.")
        if result.execution_fidelity.found_on == "EMULATED":
            typer.echo("DuckDB is an approximation; these results were not checked on PostgreSQL.")
    else:
        typer.echo("The comparison did not complete; no conclusion can be drawn.")
        message = result.errors[0]["message"] if result.errors else "the result was inconclusive"
        typer.echo(message, err=True)
    typer.echo(f"Report: {output_dir / 'case_report.json'}")


_STATUS_MARKERS = {
    DivergenceStatus.NOT_FOUND_WITHIN_BUDGET: ".",
    DivergenceStatus.COUNTEREXAMPLE_FOUND: "C",
    DivergenceStatus.INCONCLUSIVE: "?",
    DivergenceStatus.UNSUPPORTED: "U",
}


def _validity_label(case: CaseReport) -> str:
    tiers = set(case.validity.tiers)
    if "DOMAIN_VALIDATED" in tiers:
        return "domain-validated"
    if "STRUCTURAL" in tiers:
        return "schema-valid"
    return {"INVALID": "invalid", "INDETERMINATE": "validity-indeterminate"}.get(
        case.validity.status, "validity-not-assessed"
    )


def _print_suite_output(
    result: AuditReport,
    *,
    output_dir: Path,
    written: list[Path],
    verbose: bool,
    quiet: bool,
) -> None:
    if not quiet:
        markers = "".join(_STATUS_MARKERS[case.divergence_status] for case in result.cases)
        typer.echo(f"{markers} [{result.totals.cases}/{result.totals.cases}]")
        typer.echo(
            "Legend: . no difference found in tested states  C counterexample  ? inconclusive  "
            "U unsupported"
        )
    typer.echo(_suite_totals(result))
    if not quiet:
        shown = (
            result.cases
            if verbose
            else [
                c
                for c in result.cases
                if c.divergence_status is not DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
            ]
        )
        if shown:
            typer.echo("")
            typer.echo("Cases:" if verbose else "Review:")
            width = max(len(case.case_id or "unnamed") for case in shown)
            for case in shown:
                marker = _STATUS_MARKERS[case.divergence_status]
                typer.echo(
                    f"  {marker} {case.case_id or 'unnamed':<{width}}  {_case_summary(case)}"
                )
    typer.echo(f"Reports: {output_dir}")
    if verbose and written:
        typer.echo("")
        typer.echo("Artifacts:")
        for path in written:
            typer.echo(f"  Wrote {path}")


def _suite_totals(result: AuditReport) -> str:
    counts = result.totals.by_divergence_status
    total = result.totals.cases
    agreements = counts.get("NOT_FOUND_WITHIN_BUDGET", 0)
    counterexamples = counts.get("COUNTEREXAMPLE_FOUND", 0)
    return (
        f"{total} {_plural(total, 'case')} | "
        f"{agreements} {_plural(agreements, 'agreement')} | "
        f"{counterexamples} {_plural(counterexamples, 'counterexample')} | "
        f"{counts.get('INCONCLUSIVE', 0)} inconclusive | {counts.get('UNSUPPORTED', 0)} unsupported"
    )


def _case_summary(case: CaseReport) -> str:
    if case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET:
        return "agreement on tested states"
    if case.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND:
        generator = str(case.findings[0].divergence.get("generator", "source unavailable"))
        return f"counterexample | {_validity_label(case)} | {generator.replace('_', '-')}"
    return case.headline


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"


@agents_app.command("run")
def agents_run_command(
    scenario: Annotated[
        str, typer.Option(help="module:attr or file.py:attr. The referenced code is executed.")
    ],
    agent_command: Annotated[
        str,
        typer.Option(
            help="Command that accepts an MCP configuration. {mcp_config}, {task_file} and "
            "{run_dir} are substituted into its arguments."
        ),
    ],
    trust_code: Annotated[
        bool, typer.Option("--trust-code", help="Required: confirm the scenario is trusted code.")
    ] = False,
    worlds: Annotated[
        str, typer.Option(help="generated, fixed (hand-written regression worlds) or all.")
    ] = "generated",
    trials: Annotated[
        int,
        typer.Option(
            min=1,
            help="Runs per world; also the baseline run count unless --baseline-trials is set.",
        ),
    ] = 4,
    baseline_trials: Annotated[
        int | None,
        typer.Option(min=1, help="Baseline runs, when they should differ from --trials."),
    ] = None,
    timeout: Annotated[float, typer.Option(min=0.001, help="Seconds per agent run.")] = 300.0,
    max_worlds: Annotated[
        int,
        typer.Option(
            min=1,
            help="Safety cap on generated worlds, picked for coverage and run in priority order.",
        ),
    ] = 50,
    only: Annotated[
        list[str] | None, typer.Option("--world", help="Run only this world id (repeatable).")
    ] = None,
    attempts: Annotated[
        int,
        typer.Option(
            min=1,
            help="Candidate worlds the generation may visit (a scenario whose reference procedure "
            "runs a real server needs a small number).",
        ),
    ] = 20_000,
    ranking: Annotated[
        str,
        typer.Option(help="Order of live runs: diverse (default), screening, coverage or random."),
    ] = "diverse",
    stratum_patience: Annotated[
        int,
        typer.Option(
            min=0, help="Stop a stratum after this many worlds without a finding (0 = never)."
        ),
    ] = 10,
    run_patience: Annotated[
        int,
        typer.Option(
            min=0,
            help="Stop the run after this many consecutive worlds with no new feature and no "
            "finding (0 = never).",
        ),
    ] = 30,
    max_trials: Annotated[
        int, typer.Option(min=1, help="Most paired runs the sequential test may use per world.")
    ] = 16,
    hints: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="A hints file from `agents hints propose`: confirmed hints count as declared, "
            "the others as proposed (they prioritize, and grant no validity tier).",
        ),
    ] = None,
    sequential: Annotated[
        bool, typer.Option(help="Stop each world when a sequential test decides.")
    ] = True,
    minimize: Annotated[
        bool,
        typer.Option(
            help="Minimize the mutation path of each finding with repeated runs (costs runs)."
        ),
    ] = False,
    max_money: Annotated[
        float | None, typer.Option(min=0, help="Stop when the reported cost reaches this.")
    ] = None,
    max_runs: Annotated[
        int | None, typer.Option(min=1, help="Stop after this many agent runs.")
    ] = None,
    max_seconds: Annotated[
        float | None, typer.Option(min=1, help="Stop after this much wall time.")
    ] = None,
    output_dir: Annotated[Path, typer.Option()] = Path("artifacts/agents-run"),
    fail_on: Annotated[AgentsFailOn, typer.Option()] = AgentsFailOn.NONE,
) -> None:
    """Run an agent on the baseline and on every valid world of a scenario."""
    from isitright.core.stochastic import Budget
    from isitright.packs.mcp.audit import run_scenario
    from isitright.packs.mcp.model import ScenarioError
    from isitright.packs.mcp.runner import AgentsInputError
    from isitright.packs.mcp.screening import StoppingRules

    if worlds not in {"generated", "fixed", "all"}:
        raise typer.BadParameter("worlds must be generated, fixed or all")
    if ranking not in {"screening", "diverse", "coverage", "random"}:
        raise typer.BadParameter("ranking must be screening, diverse, coverage or random")
    progress = _RunProgress()
    typer.echo(f"Generating worlds (up to {attempts} candidates)...", err=True)

    def generation_progress(visited: int, valid: int, limit: int) -> None:
        typer.echo(f"  {visited} of {limit} candidates visited, {valid} valid", err=True)

    typer.echo(f"Agent runs: {progress.LEGEND}", err=True)
    try:
        report = run_scenario(
            scenario_ref=scenario,
            agent_command=agent_command,
            output_dir=output_dir,
            worlds=worlds,  # type: ignore[arg-type]
            k=trials,
            baseline_trials=baseline_trials,
            timeout_seconds=timeout,
            trust_code=trust_code,
            max_worlds=max_worlds,
            attempts=attempts,
            only=only,
            budget=Budget(money=max_money, runs=max_runs, seconds=max_seconds),
            ranking=ranking,  # type: ignore[arg-type]
            rules=StoppingRules(stratum_patience or None, run_patience or None),
            sequential=sequential,
            max_trials=max_trials,
            minimize=minimize,
            hints_file=hints,
            progress=progress.update,
            generation_progress=generation_progress,
        )
        progress.finish()
    except (AgentsInputError, ScenarioError, OSError) as error:
        progress.finish()
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    except Exception as error:
        progress.finish()
        typer.echo(f"Agent run error: {error}", err=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from error
    case = report.cases[0]
    typer.echo(case.headline)
    controls = case.controls.status if case.controls else "NOT_APPLICABLE"
    typer.echo(f"Status: {case.divergence_status.value}. Controls: {controls}.")
    for note in case.search.notes:
        if "ranked by" in note:
            typer.echo(f"Worlds: {note}.")
    stopping = case.search.stopping
    if stopping is not None and stopping.run_stop_reason:
        typer.echo(f"Stopped: {stopping.run_stop_reason}.")
    typer.echo(f"Runs: {progress.runs}. Elapsed: {progress.elapsed()}.")
    typer.echo(f"Report: {output_dir / 'report.json'}")
    if case.divergence_status is DivergenceStatus.UNSUPPORTED:
        raise typer.Exit(EXIT_INVALID_INPUT)
    if case.divergence_status is DivergenceStatus.INCONCLUSIVE:
        raise typer.Exit(EXIT_INTERNAL_ERROR)
    if fail_on is AgentsFailOn.ANY_FINDING and case.findings:
        raise typer.Exit(EXIT_POLICY_TRIGGERED)
    if fail_on is AgentsFailOn.INVARIANT and any(
        o.kind == "INVARIANT" for f in case.findings for o in f.oracles
    ):
        raise typer.Exit(EXIT_POLICY_TRIGGERED)


@hints_app.command("propose")
def hints_propose_command(
    scenario: Annotated[str, typer.Option(help="module:attr or file.py:attr (executed).")],
    proposer: Annotated[
        str, typer.Option(help="module:attr of a HintProposer (executed; it may call a model).")
    ],
    output: Annotated[Path, typer.Option(help="YAML file to write.")] = Path("hints.yaml"),
    trust_code: Annotated[
        bool, typer.Option("--trust-code", help="Required: the scenario and proposer are code.")
    ] = False,
) -> None:
    """Ask a proposer for hints from the task, policy and tool schemas, and write them to a file."""
    from isitright.core.proposals import ProposalRequest, propose_hints, write_proposals
    from isitright.packs.mcp.model import ScenarioError, load_proposer, load_scenario

    if not trust_code:
        typer.echo(
            "Proposing hints executes the scenario and proposer code; pass --trust-code.", err=True
        )
        raise typer.Exit(EXIT_INVALID_INPUT)
    if output.exists():
        typer.echo("output file already exists; choose a new file", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    try:
        loaded = load_scenario(scenario)
        request = ProposalRequest(
            task=loaded.task,
            policy=loaded.spec.policy,
            tools=loaded.spec.tools,
            schema=loaded.spec.schema,
            existing=list(loaded.hints),
        )
        result = propose_hints(load_proposer(proposer), request)
        write_proposals(output, result, scenario=loaded.id)
    except ScenarioError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo(
        f"{len(result.hints)} hint(s) proposed, {len(result.rejected)} rejected by the entity "
        f"model. Edit {output}, then run: isitright agents hints confirm {output}"
    )


@hints_app.command("confirm")
def hints_confirm_command(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    accept: Annotated[
        list[str] | None, typer.Option("--accept", help="Confirm only this hint (repeatable).")
    ] = None,
    scenario: Annotated[
        str | None,
        typer.Option(help="Re-check each hint against this scenario first (executes it)."),
    ] = None,
    trust_code: Annotated[
        bool, typer.Option("--trust-code", help="Required with --scenario.")
    ] = False,
) -> None:
    """Mark proposed hints confirmed: they are then used as declared hints."""
    from isitright.core.proposals import ProposalError, confirm_proposals
    from isitright.packs.mcp.model import ScenarioError, load_scenario

    try:
        schema = existing = None
        if scenario is not None:
            if not trust_code:
                typer.echo("--scenario executes the scenario; pass --trust-code.", err=True)
                raise typer.Exit(EXIT_INVALID_INPUT)
            loaded = load_scenario(scenario)
            schema, existing = loaded.spec.schema, list(loaded.hints)
        done = confirm_proposals(file, accept, schema=schema, existing=existing or ())
    except (ProposalError, ScenarioError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo(f"Confirmed {len(done)} hint(s): {', '.join(done) or 'none'}")


@agents_app.command("order")
def agents_order_command(
    report: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    trust_code: Annotated[
        bool, typer.Option("--trust-code", help="Required: confirm the scenario is trusted code.")
    ] = False,
    random_seeds: Annotated[int, typer.Option(min=1, help="Random orders to average over.")] = 100,
) -> None:
    """Where the findings of a finished run sit under each world ordering (offline, free).

    Re-ranks the worlds the run executed with screening, diverse, coverage and random orders and
    reports how many worlds each needs before the first finding. Only executed worlds count.
    """
    from isitright.packs.mcp.model import ScenarioError, load_scenario
    from isitright.packs.mcp.ordering import OrderingError, compare_orderings

    if not trust_code:
        typer.echo("This executes the scenario's code; pass --trust-code.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    try:
        data = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
        scenario = load_scenario(data.cases[0].extensions["mcp"]["scenario_ref"])
        results = compare_orderings(data, report.parent, scenario, random_seeds=random_seeds)
    except (OrderingError, ScenarioError, OSError, KeyError) as error:
        typer.echo(f"Ordering error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo("ranking     worlds  findings  first finding (mean / worst)  seeds")
    for r in results:
        first = (
            "-" if r.first_finding is None else f"{r.first_finding:.1f} / {r.first_finding_worst}"
        )
        typer.echo(f"{r.ranking:<11} {r.worlds:>6}  {r.findings:>8}  {first:<28}  {r.seeds:>5}")
    typer.echo("Only worlds the run executed are placed; an early-stopped run is biased.")


@agents_app.command("replay")
def agents_replay_command(
    report: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    trust_code: Annotated[
        bool, typer.Option("--trust-code", help="Required: confirm the scenario is trusted code.")
    ] = False,
    findings_only: Annotated[bool, typer.Option(help="Replay only runs behind a finding.")] = False,
) -> None:
    """Replay recorded runs offline and check they reproduce."""
    from isitright.packs.mcp.replay import replay_report as replay_runs

    if not trust_code:
        typer.echo("Replay executes the scenario's code; pass --trust-code.", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT)
    try:
        data = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
        outcomes = replay_runs(data, None, report.parent, findings_only=findings_only)
    except Exception as error:
        typer.echo(f"Replay error: {error}", err=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from error
    for outcome in outcomes:
        mark = "reproduced" if outcome.reproduced else "NOT reproduced"
        typer.echo(f"{outcome.world_id}/{outcome.trial}: {mark}. {outcome.detail}")
    if not all(o.reproduced for o in outcomes):
        raise typer.Exit(EXIT_INTERNAL_ERROR)


@agents_app.command("export")
def agents_export_command(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option(help="JSONL file to append eval cases to.")],
) -> None:
    """Export a report's findings as new eval cases (world, task, recorded trace, verdict)."""
    from isitright.packs.mcp.audit import export_eval_cases

    try:
        data = AuditReport.model_validate_json(report.read_text(encoding="utf-8"))
        cases = export_eval_cases(
            data.cases[0].extensions["mcp"]["scenario_ref"], data, report.parent
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")
    except Exception as error:
        typer.echo(f"Export error: {error}", err=True)
        raise typer.Exit(EXIT_INVALID_INPUT) from error
    typer.echo(f"Exported {len(cases)} eval case(s) to {output}")


if __name__ == "__main__":
    app()
