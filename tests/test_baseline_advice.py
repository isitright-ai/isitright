"""P3: the advice on baseline runs is the one the simulation supports.

At the default test (alpha 0.05, alternative 0.8) a world compared with 7 real baseline runs can
reach the upper boundary only if nearly every pair is discordant, so a realistic rise in failures is
almost never detected. 16 baseline runs detect a rise from 10% to 70% most of the time.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from isitright.core.sequential import Decision, PairedSprt, SprtConfig

ROOT = Path(__file__).parents[1]
TRIALS = 4000


def _power(baseline_runs: int, baseline_rate: float, world_rate: float, seed: int) -> float:
    rng = random.Random(seed)
    detected = 0
    for _ in range(TRIALS):
        test = PairedSprt(SprtConfig(min_pairs=min(4, baseline_runs), max_pairs=baseline_runs))
        for _ in range(baseline_runs):
            test.add(rng.random() < baseline_rate, rng.random() < world_rate)
            if test.decision is not Decision.CONTINUE:
                break
        detected += test.decision is Decision.RATE_INCREASE
    return detected / TRIALS


def test_the_figures_quoted_in_the_docs_come_from_this_simulation() -> None:
    seven = _power(7, 0.10, 0.70, seed=7)
    sixteen = _power(16, 0.10, 0.70, seed=16)
    assert 0.02 <= seven <= 0.055, seven  # "3.7%"
    assert 0.82 <= sixteen <= 0.90, sixteen  # "86%"


def _advice_files() -> list[Path]:
    return [*sorted((ROOT / "docs").rglob("*.md")), ROOT / "CHANGELOG.md", ROOT / "README.md"]


def test_no_text_in_the_repository_advises_seven_baseline_runs() -> None:
    pattern = re.compile(r"(raise|increase|use)[^.\n]{0,60}\b7 or more\b", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path in _advice_files()
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
    for path in [*_advice_files(), *(ROOT / "src").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "baseline runs to 7" not in text, path


def _power_by_pairs(max_pairs: int, min_pairs: int, seed: int) -> float:
    """Pairs made of fresh runs (0.9): a rise from 10% to 70%, up to ``max_pairs`` pairs."""
    rng = random.Random(seed)
    detected = 0
    for _ in range(TRIALS):
        test = PairedSprt(SprtConfig(min_pairs=min_pairs, max_pairs=max_pairs))
        for _ in range(max_pairs):
            test.add(rng.random() < 0.10, rng.random() < 0.70)
            if test.decision is not Decision.CONTINUE:
                break
        detected += test.decision is Decision.RATE_INCREASE
    return detected / TRIALS


def test_the_pair_limit_figures_in_the_docs_come_from_this_simulation() -> None:
    assert 0.35 <= _power_by_pairs(10, 3, seed=10) <= 0.43  # "about 40%"
    assert 0.82 <= _power_by_pairs(16, 4, seed=16) <= 0.90  # "about 85%"
    assert 0.91 <= _power_by_pairs(20, 4, seed=20) <= 0.97  # "about 94%"
    assert 0.88 <= _power_by_pairs(20, 3, seed=21) <= 0.94  # "about 91%"


def test_the_live_agents_page_and_the_changelog_give_the_pair_limit_and_the_reason() -> None:
    page = (ROOT / "docs" / "concepts" / "live-agents.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog.split("## 0.9")[1].split("## 0.8.1")[0]
    assert re.search(r"20\s+pairs", page) and "about 94%" in page and "about 91%" in page
    assert "fresh" in page and "baseline run" in page
    assert re.search(r"20\s+in\s+all\s+three\s+packs", section), "the changelog names 20 pairs"
    for figure in ("about 40%", "about 85%", "about 94%", "about 91%"):
        assert figure in section, f"the reason quotes the simulation: {figure}"
