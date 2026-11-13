"""Replay a research finding offline from its artifact, and write reports and exports.

Replay rebuilds the minimized corpus and the frozen index statistics from the artifact and checks
three things: the recorded tool calls give the same results on the rebuilt world (so the world is
the one the run saw), the recorded report still earns the recorded verdict from the oracles, and,
for a stand-in agent, running the agent again with the recorded seed gives the same report. A live
agent is never run again by replay: its recorded run is what is replayed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isitright.core.evidence import AuditReport, CaseReport, EvalCase, Totals, totals_of
from isitright.core.mutations import World
from isitright.core.replay import (
    ReplayArtifact,
    ReplayResult,
    load_artifact,
    replay,
    write_artifact,
)
from isitright.packs.research.agents import STAND_INS, ResearchTask, ToolClient
from isitright.packs.research.documents import COLLECTION
from isitright.packs.research.oracle import judge
from isitright.packs.research.retrieval import FrozenStats, ToolHost, build_index
from isitright.packs.research.runs import RecordedRun


def rerun(artifact: ReplayArtifact) -> dict[str, Any]:
    world = World.from_json(artifact.world)
    stats = FrozenStats.from_json(artifact.host["index_stats"])
    inputs = artifact.inputs
    task = ResearchTask.model_validate(inputs["task"])
    baseline = RecordedRun.model_validate(inputs["baseline_run"])
    recorded = RecordedRun.model_validate(inputs["world_run"])
    docs = list(world.state.entities(COLLECTION))
    host = ToolHost(build_index(stats, docs), world.response_edits)
    trace_ok = True
    for event in recorded.trace:
        if event["name"] not in ToolHost.TOOLS:
            continue
        text, error = host.try_call(event["name"], event["arguments"])
        if text != event["result"] or error != event["is_error"]:
            trace_ok = False
    verdict = judge(world, recorded, baseline, inputs.get("fact"), task.answer_type)
    observed: dict[str, Any] = {
        "outcome": verdict.outcome.value,
        "expectation": verdict.expectation.kind.value,
        "behavior": verdict.behavior.value,
        "trace_reproduced": trace_ok,
    }
    subject = inputs["subject"]
    name = str(subject["name"]).split("(")[0]
    if subject["kind"] == "stand_in" and name in STAND_INS and recorded.seed is not None:
        again_host = ToolHost(build_index(stats, docs), world.response_edits)
        agent = STAND_INS[name](task)
        report = agent.run(ToolClient(again_host), task, recorded.seed)
        observed["subject_rerun_same_report"] = report == recorded.report
    return observed


def export_case(artifact: ReplayArtifact) -> dict[str, Any]:
    """A finding as a new eval case: the minimized corpus, the question, and the expectation.

    The expectation is recomputed from the artifact's world with the reference procedure, so an
    export read from an artifact on disk equals the one made at audit time.
    """
    world = World.from_json(artifact.world)
    inputs = artifact.inputs
    task = ResearchTask.model_validate(inputs["task"])
    baseline = RecordedRun.model_validate(inputs["baseline_run"])
    recorded = RecordedRun.model_validate(inputs["world_run"])
    verdict = judge(world, recorded, baseline, inputs.get("fact"), task.answer_type)
    expectation = verdict.expectation.to_json()
    return {
        "pack": "research",
        "case_id": artifact.case_id,
        "source_finding": artifact.case_id,
        "payload": {
            "corpus": [dict(d) for d in world.state.entities(COLLECTION)],
            "params": dict(world.state.params),
            "question": task.question,
            "answer_type": task.answer_type,
            "response_edits": [e.model_dump(mode="json") for e in world.response_edits],
        },
        "expectation": {
            **expectation,
            "statement": _statement(expectation),
            "oracle": "constructive reference procedure over the corpus, plus a citation check",
        },
    }


def _statement(expectation: dict[str, Any]) -> str:
    kind = expectation.get("kind")
    value = expectation.get("value")
    return {
        "KEEP": f"the answer stays {value!r}",
        "KEEP_OR_FLAG": f"the answer stays {value!r}, or the report states that sources conflict",
        "NEWER": (
            f"the report gives the newer value {value!r}, or states the newer source or conflict"
        ),
        "ABSTAIN_OR_FLAG": "the report abstains, or states that the source is gone or retracted",
    }.get(str(kind), "")


def replay_file(path: Path) -> ReplayResult:
    return replay(load_artifact(path), rerun)


def write_outputs(
    out_dir: Path,
    report: CaseReport,
    artifacts: dict[str, ReplayArtifact],
    exports: dict[str, dict[str, Any]],
    cannot_judge: list[dict[str, Any]] | None = None,
) -> list[Path]:
    """Write the report, a replay artifact and an eval case per finding, findings-cases.md, and
    (when any run could not be judged) cannot-judge.jsonl with every such run's full answer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for finding in report.findings:
        number = finding.finding_id.rsplit(":", 1)[1]
        artifact = artifacts[finding.finding_id]
        path = out_dir / f"{number}.replay.json"
        digest = write_artifact(path, artifact)
        finding.replay.artifact = path.name
        finding.replay.artifact_sha256 = digest
        finding.replay.command = f"isitright research replay {path.name}"
        export = EvalCase.model_validate(exports[finding.finding_id])
        export_path = out_dir / f"{number}.eval-case.json"
        export_path.write_text(
            json.dumps(export.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", "utf-8"
        )
        written.extend([path, export_path])
    audit = AuditReport(
        schema_version="0.8",
        pack="research",
        kind="case",
        cases=[report],
        totals=totals_of([report]),
        elapsed_seconds=report.elapsed_seconds,
        metadata={"pack": "research"},
    )
    report_path = out_dir / "report.json"
    report_path.write_text(
        json.dumps(audit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", "utf-8"
    )
    cases = out_dir / "findings-cases.md"
    cases.write_text(cases_markdown(report), encoding="utf-8")
    extra: list[Path] = []
    if cannot_judge:
        listing = out_dir / "cannot-judge.jsonl"
        listing.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in cannot_judge),
            encoding="utf-8",
        )
        extra.append(listing)
    return [report_path, cases, *written, *extra]


def _doc_block(doc: dict[str, Any]) -> str:
    meta = ", ".join(f"{k}={doc[k]}" for k in ("date", "source") if doc.get(k))
    prov = doc.get("provenance")
    tag = f" [added by {prov['kind']}]" if prov else ""
    return f"- `{doc['id']}`{tag} ({meta}): {doc['text']}"


def cases_markdown(report: CaseReport) -> str:
    """One block per finding with the question, the documents, both reports and the verdict side
    by side, for a person to read. Everything here comes from the report."""
    ext = report.extensions.get("research", {})
    lines = [
        f"# Findings: {report.case_id}",
        "",
        f"Subject: {ext.get('subject_statement', '')} ({ext.get('subject', {}).get('name', '')}).",
        f"Mode: {ext.get('mode')}. Status: {report.divergence_status.value}.",
        "",
    ]
    classes = {c["finding"]: c for c in ext.get("proposed_classification", [])}
    for finding in report.findings:
        d = finding.divergence
        before = d.get("baseline_report", d.get("recorded_report"))
        level = (d.get("citations") or {}).get("level_reached")
        lines += [
            f"## {finding.finding_id}",
            "",
            f"Question: {d['question']}",
            "",
            f"Mutation path: {' ; '.join(m.description for m in finding.mutation_path)}",
            "",
            "Documents in the shown world:",
            *[_doc_block(x) for x in d["documents_in_world"]],
            "",
            f"Report before (baseline): `{json.dumps(before)}`",
            "",
            f"Report in the world: `{json.dumps(d.get('world_report', d.get('recorded_report')))}`",
            "",
            f"Expected: {json.dumps(d['expectation'])}",
            f"Oracle messages: {'; '.join(d['oracle_messages'])}",
            f"Behavior: {d.get('behavior')}; citation level: {level}",
            f"Reference: {d['reference_trust']}",
            f"Shown world is minimized: {d['shown_world_is_minimized']}; "
            f"reproduces on it: {d['reproduces_on_shown_world']}",
            f"Scope: {d['scope']}",
        ]
        if finding.finding_id in classes:
            c = classes[finding.finding_id]
            lines.append(
                f"Proposed classification (by the implementing assistant, not a verdict): "
                f"{c['class']} -- {c['why']}"
            )
        lines.append("")
    if not report.findings:
        lines.append("No findings.")
    skipped = ext.get("cannot_judge") or {}
    if skipped.get("runs"):
        lines += [
            "## Runs not judged (CANNOT_JUDGE)",
            "",
            f"{skipped['runs']} run(s) could not be judged: the answer could not be read as the "
            "declared kind, or no right answer is defined in that world. Counts per mutator: "
            f"{json.dumps(skipped['by_mutator'])}. Not judged is not right: a high count in one "
            "family means the audit is incomplete there. Full list with every answer: "
            "`cannot-judge.jsonl` beside this file.",
            "",
        ]
        for family, rows in skipped["examples"].items():
            for row in rows:
                lines.append(f"- {family}: `{row['answer']}` -- {row['reason']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def load_report(path: Path) -> AuditReport:
    return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["Totals", "cases_markdown", "load_report", "replay_file", "rerun", "write_outputs"]
