"""The agent's own retriever against the simulated one, on the same queries (0.9).

Proposed fixture: pending owner review (the agent's "own" results are written by Claude).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isitright.packs.research.external import _read_own_retrieval
from isitright.packs.research.runs import RecordedRun, SubjectLabel

from .research_fixtures import audit, run_stand_in

QUERY = "Halvorsen Bridge completed"


def run(own: list[dict[str, Any]]) -> RecordedRun:
    label = SubjectLabel(kind="live_agent", name="x", note="")
    return RecordedRun(subject=label, task_id="t", question="q", own_retrieval=own)


def ours(ids: int = 3) -> list[str]:
    a = audit()
    return a.replay_queries(a.base, [{"query": QUERY, "k": ids}])[0]


def test_an_agent_that_gives_no_results_is_counted_not_guessed() -> None:
    got = audit().own_retriever_fidelity([run([]), run([])])
    assert got == {
        "runs_with_own_retrieval": 0,
        "runs": 2,
        "note": "the agent gave no results of its own retriever: nothing to compare",
    }


def test_the_same_queries_are_compared_as_counts_with_no_threshold() -> None:
    mine = ours()
    same = {"query": QUERY, "ids": mine}
    swapped = {"query": QUERY, "ids": [mine[1], mine[0], mine[2]]}
    other = {"query": QUERY, "ids": ["bridge-westgate", "nothing-1", "nothing-2"]}
    got = audit().own_retriever_fidelity([run([same, swapped]), run([other])])
    assert (got["queries"], got["same_top1"], got["same_top5_set"]) == (3, 1, 2)
    assert got["runs_with_own_retrieval"] == 2 and got["runs"] == 2
    assert "threshold" not in json.dumps(got) and "high" not in json.dumps(got)
    assert got["mean_overlap_at_5"] == round((1 + 1 + 0) / 3, 3)


def test_the_stand_in_report_says_nothing_to_compare() -> None:
    _, report = run_stand_in("careful", depth=1)
    own = report.extensions["research"]["own_retriever_fidelity"]
    assert own["runs_with_own_retrieval"] == 0 and "nothing to compare" in own["note"]


def test_the_agents_own_results_file_is_read_line_by_line(tmp_path: Path) -> None:
    path = tmp_path / "own_retrieval.jsonl"
    path.write_text(
        '{"query": "a", "ids": ["x", "y"]}\n'
        "not json\n"
        '{"query": "b", "ids": "x"}\n'
        '{"query": 3, "ids": []}\n'
        '{"query": "d", "ids": [1, 2]}\n'
        '{"query": "c", "ids": ["z"], "extra": 1}\n',
        encoding="utf-8",
    )
    assert _read_own_retrieval(path) == [
        {"query": "a", "ids": ["x", "y"]},
        {"query": "c", "ids": ["z"]},
    ]
    assert _read_own_retrieval(tmp_path / "missing.jsonl") == []
