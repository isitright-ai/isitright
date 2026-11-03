"""The seeded rule that picks the benchmark questions, fixed before any program was run.

Rule (stated in the 0.6 notes before any run):
  universe  all 257 questions of da-dev-questions.jsonl
  eligible  the data file is at most 100 KB (keeps worlds small and runs fast) and the concept tags
            do not include "Machine Learning" (model fitting and random splits are not closed-form)
  sample    per difficulty level (easy, medium, hard), 14 questions drawn uniformly without
            replacement from the eligible ids sorted ascending, with random.Random(SEED)
  SEED      20261102
Writes selection.json (ids by level) next to this file. Reads the benchmark as data only.

    python select_tasks.py <dabench data dir>
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

SEED = 20261102
PER_LEVEL = 14
MAX_BYTES = 100_000


def select(data: Path) -> dict[str, list[int]]:
    questions = [
        json.loads(line)
        for line in (data / "da-dev-questions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    eligible = [
        q
        for q in questions
        if (data / "da-dev-tables" / q["file_name"]).stat().st_size <= MAX_BYTES
        and "Machine Learning" not in q["concepts"]
    ]
    rng = random.Random(SEED)
    chosen: dict[str, list[int]] = {}
    for level in ("easy", "medium", "hard"):
        ids = sorted(q["id"] for q in eligible if q["level"] == level)
        chosen[level] = sorted(rng.sample(ids, PER_LEVEL))
    return chosen


if __name__ == "__main__":
    result = select(Path(sys.argv[1]))
    out = Path(__file__).with_name("selection.json")
    out.write_text(
        json.dumps({"seed": SEED, "per_level": PER_LEVEL, "ids": result}, indent=2) + "\n"
    )
    print(json.dumps(result))
