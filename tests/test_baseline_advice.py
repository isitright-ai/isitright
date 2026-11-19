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


def test_the_live_agents_page_and_the_changelog_say_16_and_give_the_reason() -> None:
    page = (ROOT / "docs" / "concepts" / "live-agents.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for text in (page, changelog):
        section = text.split("## 0.8.1")[1].split("## 0.8.0")[0] if text is changelog else text
        assert re.search(r"16 baseline\s+runs", section), "the advice names 16 baseline runs"
        assert "86%" in section and "3.7%" in section, "the reason quotes the simulation"
    assert "--baseline-runs 16 --max-trials 16" in page  # the data pack caps runs at --max-trials
    assert "--runs 16" in page  # the research pack
