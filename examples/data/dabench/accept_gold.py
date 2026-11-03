# Proposed fixture: pending owner review
"""Accept a gold program only if it reproduces the benchmark's recorded answer.

For each built task, run the gold program through the data host on the unmutated data and compare
each of the benchmark's ``common_answers`` with the program's answer of the same name, under the
declared tolerance (the decimals the question asks for). Every question whose gold does not
reproduce is listed with what differs: that is a result (the gold, the label or the question may
be wrong), not something to hide. Writes ``gold_acceptance.json``.

    python accept_gold.py <dabench data dir> <tasks dir> <out json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from isitright.packs.data.audit import AuditConfig, DataAudit
from isitright.packs.data.comparison import DataComparator, normal_name, to_value
from isitright.packs.data.task import load_task


def label_answers(pairs: list[list[str]]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for name, value in pairs:
        grouped.setdefault(normal_name(name), []).append(to_value(value))
    return grouped


def flatten(answer: object, out: dict[str, list[object]]) -> None:
    """Gold answers may nest (per-continent): collect every named value, in order."""
    if isinstance(answer, dict):
        for name, value in answer.items():
            if isinstance(value, dict):
                flatten(value, out)
            else:
                out.setdefault(normal_name(str(name)), []).append(to_value(value))


def decimals_of(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


def accept(data: Path, tasks: Path) -> list[dict[str, object]]:
    labels = {}
    for line in (data / "da-dev-labels.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        labels[row["id"]] = row["common_answers"]
    results = []
    for directory in sorted(tasks.iterdir(), key=lambda p: int(p.name)):
        qid = int(directory.name)
        entry: dict[str, object] = {"id": qid}
        try:
            task = load_task(directory)
            with DataAudit(task, AuditConfig(trust_code=True)) as audit:
                run = audit.host.run(task.gold, audit.prepared.base)
        except Exception as error:  # the mapper refused the data, or the task is incomplete
            entry.update(status="UNSUPPORTED", reason=f"{type(error).__name__}: {error}"[:300])
            results.append(entry)
            continue
        if run.status != "ok":
            entry.update(
                status="GOLD_DOES_NOT_RUN",
                reason=f"{run.status}: {run.error[-300:]} {run.violations[:3]} {run.stderr[-200:]}",
            )
            results.append(entry)
            continue
        got: dict[str, list[object]] = {}
        flatten(run.answer()[0], got)
        wanted = label_answers([[str(n), str(v)] for n, v in labels[qid]])
        differences = []
        for name, values in wanted.items():
            have = got.get(name)
            if have is None:
                differences.append(f"{name}: not in the gold answer")
                continue
            if values == [""] and have == [[]]:
                continue  # the label's empty answer is an empty list here
            if (
                len(values) == 1
                and isinstance(values[0], str)
                and have
                and isinstance(have[0], list)
            ):
                same = sorted(v.strip() for v in values[0].split(",")) == sorted(map(str, have[0]))
                if not same:
                    differences.append(f"{name}: label {values[0]!r}, gold {have[0]!r}")
                continue
            if len(values) > 1:  # repeated names (per group): the order of groups is not specified
                wanted_set = sorted(map(str, values))
                got_set = sorted(map(str, have))
                # a label may list only the distinct values of a repeated answer
                subset = len(wanted_set) < len(got_set) and set(wanted_set) <= set(got_set)
                if wanted_set != got_set and not subset:
                    differences.append(f"{name}: labels {wanted_set}, gold {got_set}")
                continue
            for expected, actual in zip(values, have, strict=False):
                if isinstance(expected, float):
                    places = max(
                        decimals_of(str(v)) for n, v in labels[qid] if normal_name(str(n)) == name
                    )
                    comparator = DataComparator(
                        task.policy.__class__(
                            abs_tol=10.0**-places * 1.0000001, rel_tol=0.0, basis="label decimals"
                        )
                    )
                else:
                    comparator = DataComparator(task.policy.__class__(text="normalized"))
                outcome = comparator.compare(expected, actual)
                if not outcome.matches:
                    differences.append(f"{name}: label {expected!r}, gold {actual!r}")
            if len(have) < len(values):
                differences.append(f"{name}: gold gives {len(have)} values, label {len(values)}")
        entry.update(
            status="ACCEPTED" if not differences else "NOT_REPRODUCED",
            differences=differences,
            gold_answer=run.answer()[0],
            library_versions=run.versions,
        )
        results.append(entry)
    return results


if __name__ == "__main__":
    summary = accept(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for item in summary:
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1
    print(counts)
