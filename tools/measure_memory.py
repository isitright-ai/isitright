"""Measure how far a program gets past the data host's memory limit before it is stopped.

Each case runs in a fresh process: it starts a ``DataHost`` with a 300 MB limit, runs one program,
closes the host (which reaps the runner) and reads the largest resident set of its reaped children
(``getrusage(RUSAGE_CHILDREN).ru_maxrss``): the runner's true peak. Overshoot is that peak minus the
limit. Linux and macOS only (the watchdog); on Windows the Job Object refuses the allocation itself,
which is reported instead.

    python tools/measure_memory.py [--repeat 5] [--json out.json]

CI runs it for information (``ci.yml``); the numbers are copied into ``docs/data.md``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from typing import Any

LIMIT_MB = 300
PROGRAMS = {
    "one call (bytearray 1.5 GB)": "x = bytearray(1500 * 1024 * 1024)\nresult = len(x)",
    "16 MB chunks": (
        "c = []\nfor _ in range(96):\n    c.append(bytearray(16 * 1024 * 1024))\nresult = 1"
    ),
    "numpy ones 1.5 GB": (
        "import numpy as np\nx = np.ones(1500 * 1024 * 1024, dtype=np.uint8)\nresult = 1"
    ),
}

CHILD = """
import json, resource, sys, tempfile
from pathlib import Path
from isitright.packs.data.host import DataHost
from isitright.packs.data.mapping import TableFile, read_frame
from isitright.packs.data.mapping import schema_from_frames, state_from_frames
d = Path(tempfile.mkdtemp()); (d / "t.csv").write_text("a\\n1\\n")
files = [TableFile("t.csv", "t")]; frames = {"t": read_frame(d / "t.csv")}
schema = schema_from_frames(frames, files); state = state_from_frames(frames, schema, files)
host = DataHost(schema, trust_code=True, memory_mb=%d, timeout_seconds=60)
run = host.run(sys.argv[1], state)
host.close()
scale = 1 if sys.platform == "darwin" else 1024
peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * scale
print(json.dumps({"status": run.status, "error": run.error, "peak_mb": peak / 2**20,
                  "enforcement": host.describe()["memory_enforcement"]}))
"""


def measure_once(program: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", CHILD % LIMIT_MB, program],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        return {"status": "failed", "error": completed.stderr[-400:]}
    result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--json")
    args = parser.parse_args()
    if sys.platform == "win32":
        print("Windows: the Job Object refuses an allocation over the limit (MemoryError)")
        return 0
    rows = []
    for name, program in PROGRAMS.items():
        runs = [measure_once(program) for _ in range(args.repeat)]
        over = [r["peak_mb"] - LIMIT_MB for r in runs if "peak_mb" in r]
        statuses = sorted({r["status"] for r in runs})
        row = {
            "program": name,
            "limit_mb": LIMIT_MB,
            "runs": len(runs),
            "statuses": statuses,
            "overshoot_mb_min": round(min(over), 1) if over else None,
            "overshoot_mb_median": round(statistics.median(over), 1) if over else None,
            "overshoot_mb_max": round(max(over), 1) if over else None,
            "enforcement": sorted({str(r.get("enforcement")) for r in runs}),
        }
        rows.append(row)
        print(json.dumps(row), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(
                {"platform": sys.platform, "python": sys.version.split()[0], "rows": rows}, handle
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
