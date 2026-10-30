"""Reader-oriented report files for SQL audits: JSON (schema 0.4), Markdown, fixtures, replay."""

from __future__ import annotations

import json
import os
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any

from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    DivergenceStatus,
    Finding,
    ReplayRecord,
    totals_of,
)
from isitright.core.replay import write_artifact
from isitright.packs.sql.models import (
    CanonicalValue,
    ColumnComparisonPolicy,
    ComparisonPolicy,
    QueryResult,
)
from isitright.packs.sql.replaying import artifact_from_report


class ReportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    BOTH = "both"


def case_audit(case: CaseReport) -> AuditReport:
    return AuditReport(
        pack="sql",
        kind="case",
        cases=[case],
        totals=totals_of([case]),
        elapsed_seconds=case.elapsed_seconds,
        metadata={},
    )


def write_case_report(
    result: CaseReport,
    output_dir: str | Path,
    report_format: ReportFormat = ReportFormat.BOTH,
) -> list[Path]:
    """Write requested formats plus the fixture and replay artifact; return the paths."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    case = with_artifacts(result, destination)
    if case.findings:
        fixture = destination / "counterexample.sql"
        fixture.write_text(case.findings[0].divergence["reproducer_sql"], encoding="utf-8")
        written.append(fixture)
        replay_path = destination / "replay.json"
        digest = write_artifact(replay_path, artifact_from_report(case))
        case.findings[0].replay.artifact_sha256 = digest
        written.append(replay_path)
    if report_format in {ReportFormat.JSON, ReportFormat.BOTH} or case.findings:
        path = destination / "case_report.json"
        path.write_text(_dump(case_audit(case)), encoding="utf-8")
        written.append(path)
    if report_format in {ReportFormat.MARKDOWN, ReportFormat.BOTH}:
        path = destination / "case_report.md"
        path.write_text(render_case(case), encoding="utf-8")
        written.append(path)
    return written


def write_suite_report(
    result: AuditReport,
    output_dir: str | Path,
    report_format: ReportFormat = ReportFormat.BOTH,
) -> list[Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    prepared: list[CaseReport] = []
    folders: list[Path] = []
    for index, case in enumerate(result.cases, start=1):
        folder = destination / "cases" / f"{index:04d}-{_safe(case.case_id, index)}"
        folders.append(folder)
        prepared.append(with_artifacts(case, folder))
    report = result.model_copy(update={"cases": prepared})
    written: list[Path] = []
    if report_format in {ReportFormat.JSON, ReportFormat.BOTH}:
        path = destination / "suite_report.json"
        path.write_text(_dump(report), encoding="utf-8")
        written.append(path)
    if report_format in {ReportFormat.MARKDOWN, ReportFormat.BOTH}:
        path = destination / "suite_report.md"
        path.write_text(render_suite(report), encoding="utf-8")
        written.append(path)
    for case, folder in zip(prepared, folders, strict=True):
        written.extend(write_case_report(case, folder, report_format))
    return written


def with_artifacts(case: CaseReport, destination: Path) -> CaseReport:
    """A copy whose findings name the fixture and replay files written next to the report."""
    if not case.findings:
        return case
    findings: list[Finding] = []
    for finding in case.findings:
        report_path = _display(destination / "case_report.json")
        replay = ReplayRecord(
            command=f"isitright replay {report_path}",
            artifact=_display(destination / "replay.json"),
        )
        findings.append(finding.model_copy(update={"replay": replay}))
    return case.model_copy(update={"findings": findings})


def _dump(report: AuditReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _safe(case_id: str, index: int) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (case_id or f"case-{index}"))


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return os.path.relpath(resolved, Path.cwd().resolve())
    except ValueError:
        return str(resolved)


# --- Markdown -----------------------------------------------------------------------------------


def _is_original(case: CaseReport) -> bool:
    return bool(case.findings) and case.findings[0].divergence.get("generator") == "original_state"


def _label(case: CaseReport) -> str:
    if _is_original(case):
        return "Original-data mismatch"
    if case.findings:
        return "Generated counterexample"
    if case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET:
        return "No difference found within the budget"
    if case.divergence_status is DivergenceStatus.UNSUPPORTED:
        return "Unsupported SQL"
    return "Analysis incomplete"


def _validity_text(case: CaseReport) -> str:
    tiers = set(case.validity.tiers)
    engine = case.extensions.get("sql", {}).get("execution_engine", "the engine")
    if "DOMAIN_VALIDATED" in tiers:
        return f"The evidence passed {engine} constraints and every supplied domain rule."
    if "STRUCTURAL" in tiers:
        return (
            f"The evidence passed {engine} constraints. No domain rule was supplied, so review "
            "whether the rows are plausible for this task."
        )
    if case.validity.status == "INVALID":
        return "The state violated a configured constraint and should not be used as evidence."
    if case.validity.status == "INDETERMINATE":
        return "Validation ran but could not determine whether the state was admissible."
    return "The state was not validated."


def render_case(case: CaseReport) -> str:
    lines = [
        f"# isitright case report: {case.case_id or 'unnamed case'}",
        "",
        "## Finding",
        "",
        f"**{_label(case)}.** {case.headline}",
        "",
    ]
    if case.task:
        lines.extend(["**Question:**", "", f"> {case.task}", ""])
    if case.findings:
        finding = case.findings[0]
        divergence = finding.divergence
        policy = ComparisonPolicy.model_validate(
            {k: v for k, v in case.comparison_policy.items() if k in ComparisonPolicy.model_fields}
        )
        reference = QueryResult.model_validate(divergence["reference_result"])
        candidate = QueryResult.model_validate(divergence["candidate_result"])
        lines.extend(
            [
                "**Observed difference:** "
                + explain_difference(reference, candidate, divergence["difference"], policy),
                "",
                _validity_text(case),
                "",
                "## Queries",
                "",
                "### Reference query",
                "",
                "```sql",
                case.inputs["reference_sql"],
                "```",
                "",
                "### Candidate query",
                "",
                "```sql",
                case.inputs["candidate_sql"],
                "```",
                "",
                "## Outputs on the minimized reproducer",
                "",
                "### Reference output",
                "",
                *render_result_table(reference),
                "",
                "### Candidate output",
                "",
                *render_result_table(candidate),
                "",
                "## Reproduce this finding",
                "",
                "Run this from the directory where the isitright command was launched:",
                "",
                "```console",
                finding.replay.command or "Replay command unavailable",
                "```",
                "",
                f"The fixture is `{finding.replay.artifact or 'not emitted'}` and "
                "`counterexample.sql` holds the minimized schema and rows; the JSON report "
                "retains both queries and outputs.",
                "",
                "## What to do next",
                "",
                "1. Compare the question with both SQL queries and the output difference above.",
                "2. Replay the finding to confirm it in your environment.",
                "3. Decide whether the candidate query, reference query, or task wording should "
                "change; attribution is undetermined.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                _validity_text(case),
                "",
                "## What to do next",
                "",
                "1. Review the search coverage below to see which mutation families ran.",
                "2. Increase the attempt budget or add domain constraints if important states "
                "were not exercised.",
                "3. Keep this result as bounded search evidence; it is not a proof of equivalence.",
                "",
            ]
        )
    lines.extend(_technical(case))
    return "\n".join(lines)


def _technical(case: CaseReport) -> list[str]:
    search = case.search
    match = case.original_state.get("outputs_match")
    text = "not determined" if match is None else str(match).lower()
    lines = [
        "## Technical details",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Divergence status | `{case.divergence_status.value}` |",
        f"| Validity | `{', '.join(case.validity.tiers) or case.validity.status}` |",
        f"| Execution fidelity | `{case.execution_fidelity.found_on}` "
        f"({case.execution_fidelity.engine}) |",
        f"| Review classification | `{case.attribution_status.value}` |",
        f"| Original outputs match | `{text}` |",
        f"| Search attempts | `{search.attempts}` |",
        f"| Admitted generated states | `{search.valid_candidates}` |",
        f"| Mutation families used | `{', '.join(search.families_run) or 'none'}` |",
        f"| Elapsed seconds | `{case.elapsed_seconds:.6f}` |",
        "",
    ]
    if case.original_state.get("note"):
        lines.extend(["### Original-state diagnostic", "", str(case.original_state["note"]), ""])
    if case.findings:
        finding = case.findings[0]
        info = finding.minimization
        lines.extend(
            [
                "### Counterexample construction",
                "",
                f"- Source: `{finding.divergence.get('generator')}`",
                f"- Triggering change: {finding.divergence.get('original_injected_change')}",
                f"- Minimized rows: `{info.get('rows_before')}` to `{info.get('rows_after')}`",
                f"- Minimization attempts: `{info.get('attempts')}`",
                f"- Minimization complete: `{str(info.get('complete')).lower()}`",
                "",
            ]
        )
    if search.budget_by_group:
        lines.extend(["### Budget by hint group", ""])
        for name, group in search.budget_by_group.items():
            lines.append(
                f"- {name}: {group['candidates']} candidates, {group['executed']} executed"
            )
        lines.append("")
    if case.checked_rules:
        lines.extend(["### Validation checks", ""])
        lines.extend(f"- `{rule}`" for rule in case.checked_rules)
        lines.append("")
    if case.unused_rules:
        lines.extend(["### Rules generation could not use (check-only)", ""])
        lines.extend(f"- `{rule}`" for rule in case.unused_rules)
        lines.append("")
    if case.assumptions:
        lines.extend(["### Interpretation notes", ""])
        lines.extend(f"- {note}" for note in case.assumptions)
        lines.append("")
    if case.errors:
        lines.extend(["### Errors", ""])
        lines.extend(f"- `{e['code']}` ({e['phase']}): {e['message']}" for e in case.errors)
        lines.append("")
    return lines


def render_suite(report: AuditReport) -> str:
    cases = report.cases
    by_status = Counter(c.divergence_status.value for c in cases)
    original = sum(_is_original(c) for c in cases)
    generated = sum(bool(c.findings) and not _is_original(c) for c in cases)
    lines = [
        "# isitright suite report",
        "",
        f"**{len(cases)} cases analyzed:** {original} original-data mismatches, {generated} "
        "generated counterexamples.",
        "",
        "## Totals",
        "",
        "| Divergence status | Cases |",
        "| --- | ---: |",
        *(f"| `{status}` | {count} |" for status, count in sorted(by_status.items())),
        "",
        "## Validity",
        "",
        "| Validity | Cases |",
        "| --- | ---: |",
        *(f"| `{v}` | {n} |" for v, n in report.totals.by_validity.items()),
        "",
        "## Cases, strongest evidence first",
        "",
        "| # | Case | Result | Validity | Family |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for index, case in enumerate(cases, start=1):
        family = (
            case.findings[0].mutation_path[-1].family
            if case.findings and case.findings[0].mutation_path
            else ""
        )
        lines.append(
            f"| {index} | `{case.case_id}` | {_label(case)} | "
            f"`{', '.join(case.validity.tiers) or case.validity.status}` | {family} |"
        )
    lines.extend(
        ["", "Each case folder under `cases/` holds its report, fixture and replay file.", ""]
    )
    return "\n".join(lines)


def explain_difference(
    reference: QueryResult, candidate: QueryResult, fallback: str, policy: ComparisonPolicy
) -> str:
    ref_cols = [c.name for c in reference.columns]
    cand_cols = [c.name for c in candidate.columns]
    if len(ref_cols) != len(cand_cols):
        return (
            f"Reference returns {len(ref_cols)} columns; "
            f"candidate returns {len(cand_cols)} columns."
        )
    if policy.columns is ColumnComparisonPolicy.NAMES_AND_POSITIONS and ref_cols != cand_cols:
        return f"Column names differ: reference {ref_cols!r}; candidate {cand_cols!r}."
    ref_keys = [_row_key(r) for r in reference.rows]
    cand_keys = [_row_key(r) for r in candidate.rows]
    if Counter(ref_keys) == Counter(cand_keys) and ref_keys != cand_keys:
        return (
            "Both queries return the same rows, but in a different order. "
            f"Reference starts with {_describe_row(reference, 0)}; candidate starts with "
            f"{_describe_row(candidate, 0)}."
        )
    if len(reference.rows) != len(candidate.rows):
        return (
            f"Reference returns {len(reference.rows)} rows; candidate returns "
            f"{len(candidate.rows)} rows."
        )
    for index, (a, b) in enumerate(zip(reference.rows, candidate.rows, strict=True)):
        if _row_key(a) != _row_key(b):
            return (
                f"First differing row is {index + 1}: reference {_describe_values(reference, a)}; "
                f"candidate {_describe_values(candidate, b)}."
            )
    return fallback


def _row_key(row: list[CanonicalValue]) -> str:
    return json.dumps(
        [v.model_dump(mode="json") for v in row], sort_keys=True, separators=(",", ":")
    )


def _describe_row(result: QueryResult, index: int) -> str:
    return "no row" if not result.rows else _describe_values(result, result.rows[index])


def _describe_values(result: QueryResult, row: list[CanonicalValue]) -> str:
    parts = []
    for index, value in enumerate(row):
        name = result.columns[index].name if index < len(result.columns) else f"column_{index + 1}"
        parts.append(f"{name}={_display_value(value)}")
    return "[" + ", ".join(parts) + "]"


def render_result_table(result: QueryResult, *, limit: int = 20) -> list[str]:
    if not result.columns:
        return ["_No columns returned._"]
    headers = [_cell(c.name or f"column_{i + 1}") for i, c in enumerate(result.columns)]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    if not result.rows:
        lines.append("| " + " | ".join("_no rows_" for _ in headers) + " |")
        return lines
    for row in result.rows[:limit]:
        values = [_cell(_display_value(v)) for v in row]
        values.extend("" for _ in range(len(headers) - len(values)))
        lines.append("| " + " | ".join(values[: len(headers)]) + " |")
    if len(result.rows) > limit:
        lines.extend(["", f"_Showing {limit} of {len(result.rows)} rows._"])
    return lines


def _display_value(value: CanonicalValue) -> str:
    if value.value is None:
        return "NULL"
    if isinstance(value.value, str):
        return value.value
    return json.dumps(value.value, ensure_ascii=False, sort_keys=True)


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
