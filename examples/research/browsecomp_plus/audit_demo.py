"""Frozen audit of the published BrowseComp-Plus BM25 + gpt-5 runs on the selected tasks.

For each selected task: restrict the world to the documents the run saw plus the gold and evidence
documents, give the pack the statistics of the whole corpus, turn the published run into a recorded
run, derive the fact span from the baseline trace (never from the gold answer), and run
`ResearchAudit.check_frozen` with a per-task time cap. Results go to a work directory outside the
repository (decoded benchmark text must not be published): per-task reports and artifacts, a
summary and cases.md.

    python audit_demo.py --data D:/Data/browsecomp-plus --work D:/Data/bcp-work
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pyarrow.parquet as pq
from common import decode_run, iter_queries, iter_runs, parse_final

from isitright.core.hints import Hint, Provenance
from isitright.packs.research.agents import ResearchTask
from isitright.packs.research.audit import AuditConfig, ResearchAudit
from isitright.packs.research.documents import COLLECTION, make_state
from isitright.packs.research.replaying import write_outputs
from isitright.packs.research.retrieval import FrozenIndex, FrozenStats
from isitright.packs.research.runs import Citation, Claim, RecordedRun, Report, SubjectLabel

TIME_CAP_SECONDS = 600.0
GOLD_BASIS = "the benchmark's published gold answer; trusted, not independently checked"
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CITE = re.compile(r"\[(\d+)\]")


def front_matter(text: str) -> dict[str, str]:
    match = _FRONT.match(text)
    out: dict[str, str] = {}
    if match:
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            out[key.strip().lower()] = value.strip()
    return out


def iso_date(value: str | None) -> str | None:
    match = re.match(r"\d{4}-\d{2}-\d{2}", value or "")
    return match.group() if match else None


def load_needed_documents(data: Path, wanted: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for file in sorted((data / "corpus").glob("*.parquet")):
        for batch in pq.ParquetFile(file).iter_batches(
            batch_size=512, columns=["docid", "text", "url"]
        ):
            for row in batch.to_pylist():
                if row["docid"] in wanted:
                    found[row["docid"]] = row
    return found


def to_document(row: dict[str, Any]) -> dict[str, Any]:
    meta = front_matter(row["text"])
    return {
        "id": row["docid"],
        "title": meta.get("title") or row["url"],
        "source": urlparse(row["url"]).netloc or None,
        "date": iso_date(meta.get("date")),
        "text": row["text"],
    }


def sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right_candidates = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    sentence = text[left + 1 if left != -1 else 0 : right + 1].strip()
    if len(sentence) > 400:  # a window that is still an exact substring of the text
        sentence = text[max(0, start - 150) : min(len(text), end + 150)]
    return sentence


def fact_span_hint(report: Report, docs: dict[str, dict[str, Any]]) -> Hint | None:
    """From the baseline trace: the first cited document that contains the run's own answer, and
    the sentence that contains it. The gold answer is not used."""
    answer = report.answer
    if not answer:
        return None
    for doc_id in report.cited_ids():
        doc = docs.get(doc_id)
        if doc is None:
            continue
        match = re.search(re.escape(answer.strip()), str(doc["text"]), re.IGNORECASE)
        if match:
            quote = sentence_around(str(doc["text"]), match.start(), match.end())
            value = match.group()
            if value in quote:
                return Hint(
                    kind="fact_span",
                    provenance=Provenance.HARVESTED_TRACE,
                    args={
                        "doc_id": doc_id,
                        "quote": quote,
                        "value": value,
                        "answer_type": "string",
                    },
                )
    return None


def recorded_run(
    decoded: dict[str, Any], docs: dict[str, dict[str, Any]], task: ResearchTask
) -> RecordedRun:
    trace = []
    for i, search in enumerate(decoded["searches"]):
        rows = [
            {
                "id": hit["docid"],
                "title": docs[hit["docid"]]["title"] if hit["docid"] in docs else hit["docid"],
                "snippet": str(hit["snippet"])[:240],
            }
            for hit in search["hits"]
        ]
        trace.append(
            {
                "index": i,
                "name": "search",
                "arguments": {"query": search["query"], "k": 5},
                "result": json.dumps({"results": rows}),
                "is_error": False,
            }
        )
    explanation, answer = parse_final(decoded["final"])
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+", explanation):
        ids = [i for i in _CITE.findall(sentence) if i in docs]
        if ids:
            claims.append(
                Claim(
                    text=sentence,
                    citations=[Citation(doc_id=i, quote="") for i in dict.fromkeys(ids)],
                )
            )
    return RecordedRun(
        subject=SubjectLabel(
            kind="recorded",
            name="BrowseComp-Plus BM25 + gpt-5 (published run)",
            written_by="published by the BrowseComp-Plus authors; not run by this tool",
            note="the run records no quotes and no open calls",
        ),
        task_id=task.id,
        question=task.question,
        trace=trace,
        report=Report(answer=answer, claims=claims),
    )


def fidelity(audit: ResearchAudit, run: RecordedRun, decoded: dict[str, Any]) -> dict[str, Any]:
    """How often our BM25 over the restricted world returns the recorded top-5 set and top-1."""
    index = FrozenIndex(audit.stats, list(audit.state.entities(COLLECTION)))
    same_set = same_top = 0
    overlap = 0.0
    total = len(decoded["searches"])
    for search in decoded["searches"]:
        recorded = [h["docid"] for h in search["hits"]]
        ours = [h.id for h in index.rank(search["query"], 5)]
        same_set += set(ours) == set(recorded)
        same_top += bool(ours) and bool(recorded) and ours[0] == recorded[0]
        overlap += len(set(ours) & set(recorded)) / max(1, len(recorded))
    return {
        "queries": total,
        "same_top5_set": same_set,
        "same_top1": same_top,
        "mean_overlap_at_5": round(overlap / total, 3) if total else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    selection = json.loads((args.work / "selection.json").read_text(encoding="utf-8"))
    ids = [i for i in selection["ids"] if not args.only or i in args.only]
    stats = FrozenStats.from_json(
        json.loads((args.work / "stats.json").read_text(encoding="utf-8"))
    )
    queries = {
        q["query_id"]: q
        for q in iter_queries(
            args.data, ("query_id", "query", "answer", "gold_docs", "evidence_docs")
        )
        if q["query_id"] in ids
    }
    runs = {
        r["query_id"]: decode_run(r)
        for r in iter_runs(args.data / "runs" / "bm25-gpt5.jsonl")
        if r["query_id"] in ids
    }
    wanted: set[str] = set()
    for qid in ids:
        wanted.update(queries[qid]["gold_docs"], queries[qid]["evidence_docs"])
        wanted.update(h["docid"] for s in runs[qid]["searches"] for h in s["hits"])
    rows = load_needed_documents(args.data, wanted)
    print(f"documents needed {len(wanted)}, found {len(rows)}", flush=True)
    summaries = []
    for qid in ids:
        q, decoded = queries[qid], runs[qid]
        started = time.monotonic()
        docs = {
            i: to_document(rows[i])
            for i in rows
            if i
            in {
                *q["gold_docs"],
                *q["evidence_docs"],
                *(h["docid"] for s in decoded["searches"] for h in s["hits"]),
            }
        }
        task = ResearchTask(
            id=f"bcp-{qid}",
            question=q["query"],
            answer_type="string",
            gold=q["answer"],
            gold_basis=GOLD_BASIS,
        )
        run = recorded_run(decoded, docs, task)
        summary: dict[str, Any] = {
            "task": task.id,
            "documents": len(docs),
            "searches": len(run.queries()),
        }
        try:
            state = make_state(docs.values())
            declared = [h] if (h := fact_span_hint(run.report, docs)) else []
            audit = ResearchAudit(
                state,
                task,
                AuditConfig(
                    depth=1, attempts=500, seconds=TIME_CAP_SECONDS, declared_hints=declared
                ),
                stats=stats,
            )
            report = audit.check_frozen(run)
            out = args.work / "out" / task.id
            write_outputs(out, report, audit.artifacts, audit.exports)
            screening = Counter()
            per_family: dict[str, Counter[str]] = {}
            for w in report.worlds:
                family = "+".join(m.family for m in w.mutation_path) or "baseline"
                cls = w.screening.screening_class if w.screening else "NONE"
                screening[cls] += 1
                per_family.setdefault(family, Counter())[
                    "UNOBSERVABLE" if w.validity.unobservable else cls
                ] += 1
            ext = report.extensions["research"]
            summary.update(
                status=report.divergence_status.value,
                fact_span=bool(declared),
                findings=[
                    {
                        "id": f.finding_id,
                        "family": f.mutation_path[-1].family,
                        "tiers": f.validity.tiers,
                        "documents_after": f.minimization.get("documents_after"),
                        "reproduces": f.divergence["reproduces_on_shown_world"],
                        "citation_level": (f.divergence.get("citations") or {}).get(
                            "level_reached"
                        ),
                    }
                    for f in report.findings
                ],
                worlds=len(report.worlds),
                screening=dict(screening),
                per_family={k: dict(v) for k, v in per_family.items()},
                skipped=report.search.families_skipped,
                baseline_citations=ext["baseline"]["citations"],
                fidelity=fidelity(audit, run, decoded),
                headline=report.headline,
            )
        except Exception as error:  # a task the pack cannot handle is accounted, with the reason
            summary.update(status="UNSUPPORTED", reason=f"{type(error).__name__}: {error}")
        summary["seconds"] = round(time.monotonic() - started, 1)
        summaries.append(summary)
        print(
            json.dumps({k: summary.get(k) for k in ("task", "status", "worlds", "seconds")}),
            flush=True,
        )
        (args.work / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
