# Proposed fixture: pending owner review.
# Written by Claude. Turns the baseline run of the owner's BigQuery steps into the "gold trusted"
# label the demo passes to isitright.
"""Write ``gold_trust.json`` from the output of step 4 (``bigquery_steps.py baseline``).

Usage:
    python -I gold_trust.py <baseline.json> [<output gold_trust.json>]

A task is "gold trusted" when the gold SQL's result on today's public data equals one of Spider's
published result files (the files are what Spider scores). A task the baseline did not run (over
the byte cap, or an error) has no entry, so the demo records its gold as unknown. The label says
how far the reference can be believed; it does not say which query is wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    baseline = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "gold_trust.json"
    trust: dict[str, dict] = {}
    for entry in baseline["tasks"]:
        if entry.get("gold_trusted") is None:
            continue
        trust[entry["id"]] = {
            "trusted": bool(entry["gold_trusted"]),
            "basis": entry["gold_trust_basis"],
        }
    target.write_text(json.dumps(trust, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    trusted = sum(1 for v in trust.values() if v["trusted"])
    print(f"{len(trust)} tasks with a label: {trusted} trusted, {len(trust) - trusted} not")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
