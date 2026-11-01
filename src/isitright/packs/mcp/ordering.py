"""How soon each world ordering reaches a finding, computed offline from a finished run.

A run visits worlds in a ranked order and stops early. Whether the ranking (screening, diverse,
coverage) beats a random order is a question about where the findings sit in each order, and the
run already holds the answer for the worlds it executed: which of them showed a finding. This
module re-ranks those worlds with each ranking and reports the position of the first finding and
the findings reached after n worlds. No agent runs and nothing is paid for.

Limits: only worlds the run executed can be placed, so a run that stopped early (patience, a
budget, ``--max-worlds``) says nothing about worlds it never reached. For an unbiased comparison,
run with patience 0 and a ``--max-worlds`` that covers the eligible worlds.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from isitright.core.evidence import AuditReport
from isitright.packs.mcp.generate import GeneratedWorld, generate_worlds
from isitright.packs.mcp.model import McpScenario
from isitright.packs.mcp.runner import read_trace
from isitright.packs.mcp.screening import Ranking, rank, screen_all

DEFAULT_RANDOM_SEEDS = 100


class OrderingError(ValueError):
    """The run cannot be re-ranked (no generated worlds, or they cannot be regenerated)."""


@dataclass
class OrderingResult:
    ranking: str
    worlds: int
    findings: int
    first_finding: float | None
    """Position (1 = first world run) of the first finding; the mean over seeds for ``random``;
    None when no world in the run had a finding."""
    first_finding_worst: int | None = None
    after: dict[int, float] = field(default_factory=dict)
    """Findings reached after n worlds (the mean over seeds for ``random``)."""
    seeds: int = 1


def compare_orderings(
    report: AuditReport,
    output_dir: Path,
    scenario: McpScenario,
    *,
    rankings: tuple[str, ...] | None = None,
    random_seeds: int = DEFAULT_RANDOM_SEEDS,
    checkpoints: tuple[int, ...] = (1, 3, 5, 10, 20),
) -> list[OrderingResult]:
    """Re-rank the generated worlds a run executed, once per ranking (many seeds for random)."""
    case = report.cases[0]
    executed = {
        w.id: bool(w.counts.get("not_met") or w.counts.get("violated"))
        for w in case.worlds
        if w.run_status == "RUN" and w.role != "BASELINE" and w.id.startswith("g")
    }
    if not executed:
        raise OrderingError("the run executed no generated world")
    generated, _ = generate_worlds(scenario, attempts=case.search.attempts, seed=case.search.seed)
    by_id: dict[str, GeneratedWorld] = {w.id: w for w in generated}
    missing = sorted(set(executed) - set(by_id))
    if missing:
        raise OrderingError(
            f"{len(missing)} executed world(s) are not generated again: "
            f"{', '.join(missing[:3])}... (a run made with hints needs the same hints, and ids "
            "from before the content-hash ids do not match)"
        )
    worlds = [by_id[i] for i in executed]
    screens = None
    trace_dir = case.search.screening.baseline_trace if case.search.screening else None
    if trace_dir is not None:
        trace = [dict(e) for e in read_trace(output_dir / trace_dir / "trace.jsonl")]
        screens = screen_all(scenario, worlds, trace)
    modes = rankings or tuple(get_args(Ranking))
    results = []
    for mode in modes:
        seeds = range(random_seeds) if mode == "random" else range(1)
        orders = [
            [executed[w.id] for w in rank(worlds, screens, mode=mode, seed=s)]  # type: ignore[arg-type]
            for s in seeds
        ]
        results.append(_summarize(mode, orders, checkpoints))
    return results


def _summarize(mode: str, orders: list[list[bool]], checkpoints: tuple[int, ...]) -> OrderingResult:
    firsts = [next((i + 1 for i, bad in enumerate(o) if bad), None) for o in orders]
    found = [f for f in firsts if f is not None]
    n = len(orders[0]) if orders else 0
    after = {c: statistics.fmean(sum(o[:c]) for o in orders) for c in checkpoints if c <= n}
    return OrderingResult(
        ranking=mode,
        worlds=n,
        findings=sum(orders[0]) if orders else 0,
        first_finding=statistics.fmean(found) if found else None,
        first_finding_worst=max(found) if found else None,
        after=after,
        seeds=len(orders),
    )
