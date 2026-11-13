# Proposed fixture: pending owner review
# Helpers that load the constructed corpus and task under examples/research (invented subjects,
# written by Claude) and build audits over them. The stand-in agents are written by Claude.
from __future__ import annotations

from pathlib import Path
from typing import Any

from isitright.core.evidence import CaseReport, Finding
from isitright.packs.research.agents import STAND_INS, ResearchTask
from isitright.packs.research.audit import AuditConfig, ResearchAudit
from isitright.packs.research.documents import load_corpus

ROOT = Path(__file__).resolve().parents[1] / "examples" / "research"


def task() -> ResearchTask:
    return ResearchTask.model_validate_json((ROOT / "task.json").read_text(encoding="utf-8"))


def corpus() -> Any:
    return load_corpus(ROOT / "corpus")


def audit(**config: Any) -> ResearchAudit:
    return ResearchAudit(corpus(), task(), AuditConfig(**config))


def run_stand_in(name: str, **config: Any) -> tuple[ResearchAudit, CaseReport]:
    a = audit(**config)
    return a, a.check(a.stand_in(STAND_INS[name](a.task)))


def single(report: CaseReport, family: str) -> list[Finding]:
    """Findings whose whole path is one mutation of ``family``."""
    return [
        f
        for f in report.findings
        if len(f.mutation_path) == 1 and f.mutation_path[0].family == family
    ]
