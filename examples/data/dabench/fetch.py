"""Fetch InfiAgent-DABench into a local cache directory. Nothing is copied into the repository.

The benchmark's code is Apache 2.0 but its data (questions, labels, tables) is CC BY-NC 4.0, so
isitright does not redistribute it. This script clones the pinned commit into an empty directory
and prints the path; later scripts read it as data and never run anything from it.

    python fetch.py [target_dir]      # default: ~/.cache/isitright/dabench
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY = "https://github.com/InfiAgent/InfiAgent"
COMMIT = "3d6c4a70198e0a41fadf539f5b43c88b8c1a2d9c"
DATA = Path("examples") / "DA-Agent" / "data"


def fetch(target: Path) -> Path:
    if not (target / ".git").exists():
        target.mkdir(parents=True, exist_ok=True)
        if any(target.iterdir()):
            raise SystemExit(f"{target} is not empty and is not a clone")
        subprocess.run(["git", "clone", "--quiet", REPOSITORY, str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "checkout", "--quiet", COMMIT], check=True)
    return target / DATA


if __name__ == "__main__":
    where = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".cache" / "isitright" / "dabench"
    )
    print(fetch(where))
