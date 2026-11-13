"""Download the BrowseComp-Plus files the demo reads into a new, empty directory.

Everything downloaded is data and is never executed. About 4.8 GB. Revisions used on 2026-11-10 are
pinned below; the runs dataset has no dataset card and no licence field (see the release notes).

    python fetch.py --data D:/Data/browsecomp-plus
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/datasets"
FILES = (
    [
        (
            f"Tevatron/browsecomp-plus/resolve/144cff8e35b5eaef7e526346aa60774a9deb941f/data/test-0000{i}-of-00006.parquet",
            f"queries/test-0000{i}-of-00006.parquet",
        )
        for i in range(6)
    ]
    + [
        (
            f"Tevatron/browsecomp-plus-corpus/resolve/b27b02bc3e45511b8b82a13e6f90ce761df726f6/data/train-0000{i}-of-00007.parquet",
            f"corpus/train-0000{i}-of-00007.parquet",
        )
        for i in range(7)
    ]
    + [
        (
            "Tevatron/browsecomp-plus-runs/resolve/3c2b136c6382d2f7d43587bbc0a77f68b024c339/bm25/gpt5.jsonl",
            "runs/bm25-gpt5.jsonl",
        )
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    if args.data.exists() and any(args.data.iterdir()):
        raise SystemExit(f"{args.data} is not empty: choose a new directory")
    for remote, local in FILES:
        target = args.data / local
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{BASE}/{remote}") as response, target.open("wb") as out:
            digest = hashlib.sha256()
            while chunk := response.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
        print(local, digest.hexdigest()[:16], flush=True)


if __name__ == "__main__":
    main()
