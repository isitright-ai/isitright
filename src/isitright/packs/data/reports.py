"""Writing, replaying and exporting data-pack reports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from isitright.core.entities import EntitySchema
from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    EvalCase,
    EvidenceGrade,
    Finding,
    describe_graded_findings,
    totals_of,
)
from isitright.core.mutations import World
from isitright.core.paths import contained_path, replay_placeholder
from isitright.core.replay import (
    ReplayArtifact,
    ReplayResult,
    load_artifact,
    replay,
    write_artifact,
)
from isitright.core.shown import check_artifact_world
from isitright.packs.data.comparison import AnswerPolicy, DataComparator
from isitright.packs.data.host import DataHost


def safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def finding_dir(finding: Finding) -> str:
    return f"findings/{safe_id(finding.finding_id)}"


def build_report(cases: list[CaseReport], elapsed: float, kind: str = "suite") -> AuditReport:
    return AuditReport(
        pack="data",
        kind="case" if len(cases) == 1 and kind != "suite" else "suite",
        cases=cases,
        totals=totals_of(cases),
        elapsed_seconds=elapsed,
        metadata={},
    )


def write_report(
    report: AuditReport, output_dir: Path, artifacts: dict[str, ReplayArtifact]
) -> None:
    """``report.json``, ``report.md``, and per finding a replay artifact and the data files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for case in report.cases:
        for finding in case.findings:
            target = contained_path(output_dir, finding_dir(finding), what="finding directory")
            target.mkdir(parents=True, exist_ok=True)
            artifact = artifacts.get(finding.finding_id)
            if artifact is not None:
                check_artifact_world(
                    artifact.world,
                    finding.world_fingerprint,
                    "replay artifact",
                    finding.finding_id,
                )
                write_artifact(target / "replay.json", artifact)
            for name, text in (finding.divergence.get("data_files") or {}).items():
                path = contained_path(target, name, what="data file name")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="")
    number = 0
    for case in report.cases:
        for finding in case.findings:
            if finding.finding_id not in artifacts:
                continue  # no artifact was written: name none and no command to run it
            number += 1
            finding.replay.artifact = f"{finding_dir(finding)}/replay.json"
            finding.replay.command = (
                f"isitright data replay {replay_placeholder(output_dir, 'report.json')} "
                f"--finding {number} --trust-code"
            )
    (output_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(markdown(report), encoding="utf-8")


def markdown(report: AuditReport) -> str:
    lines = [
        "# isitright data audit",
        "",
        "A frozen finding is scoped to a recorded program on one world. It is evidence for "
        "review, not a verdict on the agent that wrote the program.",
        "",
        "| Case | Status | Validity | Worlds executed | Rows after minimization |",
        "|---|---|---|---|---|",
    ]
    for case in report.cases:
        rows = ", ".join(str(f.minimization.get("rows_after", "-")) for f in case.findings) or "-"
        lines.append(
            f"| {case.case_id} | {case.divergence_status.value} "
            f"| {', '.join(case.validity.tiers) or case.validity.status} "
            f"| {case.search.executed} | {rows} |"
        )
    for case in report.cases:
        lines += ["", f"## {case.case_id}", "", case.headline]
        for finding in case.findings:
            if finding.mode == "live_agent":
                answers = [r["answer"] for r in finding.divergence.get("agent_runs", [])]
                lines += [
                    "",
                    f"- {finding.headline}.",
                    f"  Gold answer: {finding.divergence.get('gold_answer')!r}; "
                    f"agent answers: {answers!r}.",
                ]
            else:
                lines += [
                    "",
                    f"- {finding.headline}. Difference: {finding.divergence.get('difference')}.",
                    f"  Gold answer: {finding.divergence.get('gold_answer')!r}; "
                    f"program answer: {finding.divergence.get('program_answer')!r}.",
                ]
            if finding.replay.command:
                lines.append(
                    f"  Replay: `{finding.replay.command}` (replace the part in angle brackets "
                    "with the location of the report file)."
                    + (
                        " It replays the recorded observation; the agent is not rerun."
                        if finding.mode == "live_agent"
                        else ""
                    )
                )
        lines += describe_graded_findings(case)
        for error in case.errors:
            lines.append(f"- {error['code']}: {error['message']}")
    return "\n".join(lines) + "\n"


def replay_artifact(
    artifact: ReplayArtifact, *, trust_code: bool, timeout_seconds: float = 30.0
) -> ReplayResult:
    """Rebuild the world from the artifact and run both programs again."""
    if artifact.pack != "data":
        raise ValueError(f"not a data-pack replay artifact: {artifact.pack}")
    schema = EntitySchema.model_validate(artifact.inputs["schema"])
    world = World.from_json(artifact.world)
    host = DataHost(schema, trust_code=trust_code, timeout_seconds=timeout_seconds)
    comparator = DataComparator(_policy(artifact.inputs.get("policy", {}), artifact))
    if artifact.host.get("mode") == "live":
        return _replay_live(artifact, world, host, comparator)

    def rerun(_: ReplayArtifact) -> dict[str, Any]:
        gold = host.run(artifact.inputs["gold_code"], world.state)
        program = host.run(artifact.inputs["program_code"], world.state)
        outcome = (
            comparator.compare(gold.answer()[0], program.answer()[0])
            if gold.status == "ok" and program.status == "ok"
            else None
        )
        return {
            "differs": bool(
                gold.status == "ok"
                and (program.status == "error" or (outcome and not outcome.matches))
            ),
            "gold_answer": gold.answer()[0],
            "program_answer": program.answer()[0],
        }

    return replay(artifact, rerun)


LIVE_REPLAY_NOTE = (
    "This replays a recorded observation. The agent was not rerun: its answers are the recorded "
    "ones. Checked: the reference answer on the recorded world, the recorded comparison of each "
    "answer with it, and (for a run that returned code) what that code gives on the world."
)


def _replay_live(
    artifact: ReplayArtifact, world: World, host: DataHost, comparator: DataComparator
) -> ReplayResult:
    """Verify the recorded evidence of a live finding. No agent runs."""
    runs = artifact.inputs.get("runs", [])

    def rerun(_: ReplayArtifact) -> dict[str, Any]:
        gold = host.run(artifact.inputs["gold_code"], world.state)
        gold_answer = gold.answer()[0] if gold.status == "ok" else None
        outcomes: list[str | None] = []
        code_answers: list[Any] = []
        for record in runs:
            if record["outcome"] == "ERROR" or gold.status != "ok":
                outcomes.append(record["outcome"])
            else:
                compared = comparator.compare(gold_answer, record["answer"])
                outcomes.append(
                    "CANNOT_JUDGE"
                    if compared.inconclusive
                    else ("MET" if compared.matches else "NOT_MET")
                )
            if record.get("code") is None:
                code_answers.append(None)
            else:
                ran = host.run(record["code"], world.state)
                code_answers.append(_json_safe(ran.answer()[0]) if ran.status == "ok" else None)
        return {
            "gold_answer": _json_safe(gold_answer),
            "recorded_outcomes": outcomes,
            "code_answers": code_answers,
        }

    result = replay(artifact, rerun)
    result.details.insert(0, LIVE_REPLAY_NOTE)
    return result


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _policy(described: dict[str, Any], artifact: ReplayArtifact) -> AnswerPolicy:
    numbers = described.get("numbers", {})
    return AnswerPolicy(
        abs_tol=float(numbers.get("abs_tol", 1e-9)),
        rel_tol=float(numbers.get("rel_tol", 1e-9)),
        basis=str(numbers.get("basis", "")),
        text=str(described.get("text", "normalized")),
    )


def load_and_replay(path: Path, *, trust_code: bool) -> ReplayResult:
    return replay_artifact(load_artifact(path), trust_code=trust_code)


def export_eval_cases(
    report: AuditReport, output_dir: Path, *, include_observed: bool = False
) -> list[EvalCase]:
    """Each finding as an eval case: the dataset, the question, the gold program, the expected
    answer. Files are written under ``<output_dir>/<case>/``; the returned records index them."""
    cases = []
    for case in report.cases:
        for finding in case.findings:
            if finding.evidence_grade is EvidenceGrade.OBSERVED_FAILURE and not include_observed:
                continue
            name = safe_id(finding.finding_id)
            target = contained_path(output_dir, name, what="finding id")
            files = finding.divergence.get("data_files") or {}
            paths = {file: contained_path(target, file, what="data file name") for file in files}
            target.mkdir(parents=True, exist_ok=True)
            for file, text in files.items():
                paths[file].parent.mkdir(parents=True, exist_ok=True)
                paths[file].write_text(text, encoding="utf-8", newline="")
            (target / "gold.py").write_text(
                str(finding.divergence.get("gold_program", "")), encoding="utf-8"
            )
            live = finding.mode == "live_agent"
            expectation: dict[str, Any] = {
                "expected_answer": finding.divergence.get("gold_answer"),
                "comparison_policy": case.comparison_policy,
                "observed_program_answer": finding.divergence.get("program_answer"),
                "scope": "the finding's program on this dataset; not a statement about an agent",
            }
            if live:
                expectation.pop("observed_program_answer")
                expectation["scope"] = (
                    "the agent's own recorded runs on this dataset; the agent is not rerun by "
                    "this case"
                )
                expectation["evidence_grade"] = (
                    finding.evidence_grade.value if finding.evidence_grade else None
                )
                expectation["recorded_observation"] = {
                    "agent": (finding.divergence.get("agent") or {}),
                    "runs": finding.divergence.get("agent_runs", []),
                }
            (target / "question.txt").write_text(case.task or "", encoding="utf-8")
            (target / "expected.json").write_text(
                json.dumps(expectation, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            cases.append(
                EvalCase(
                    pack="data",
                    case_id=name,
                    source_finding=finding.finding_id,
                    payload={
                        "question": case.task,
                        "dataset": sorted(files),
                        "directory": name,
                        "gold_program": "gold.py",
                    },
                    expectation=expectation,
                )
            )
    return cases
