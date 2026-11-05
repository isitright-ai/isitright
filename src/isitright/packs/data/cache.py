"""A record of finished host runs on disk, so an interrupted frozen audit does not repeat them.

The search is deterministic for a seed, a budget and a set of results, so a restarted audit asks
for the same worlds in the same order. Each run is looked up by the hash of the code and the
fingerprint of the world; a hit replaces a process run. A miss only costs the run, so the cache can
make an audit faster but never changes what it reports.

A cache file belongs to one host configuration (timeouts, memory limit, isolation mode, the
installed packages): when that changes the file is started afresh. Runs that ended in a timeout
or a memory limit are not stored, because they depend on how loaded the machine was.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from contextlib import suppress
from dataclasses import asdict
from importlib import metadata
from pathlib import Path

from isitright.core.world import sha256_text
from isitright.packs.data.host import DataHost, RunResult

FORMAT = 1
NOT_STORED = frozenset({"timeout", "memory"})


def environment_digest() -> str:
    """A hash of the interpreter and every installed distribution with its version."""
    packages = sorted(
        {f"{(d.metadata['Name'] or '').lower()}=={d.version}" for d in metadata.distributions()}
    )
    text = json.dumps({"python": sys.version, "platform": sys.platform, "packages": packages})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def host_key(host: DataHost) -> str:
    """What a stored run depends on besides the code and the world."""
    description = {
        "format": FORMAT,
        "host": host.describe(),
        "outputs": list(host.outputs),
        "environment": environment_digest(),
    }
    return sha256_text(json.dumps(description, sort_keys=True))[:16]


def run_key(code: str, world_fingerprint: str) -> str:
    return f"{sha256_text(code)[:16]}:{world_fingerprint}"


class RunCache:
    """An append-only JSON-lines file of ``RunResult`` records, safe to lose the tail of."""

    def __init__(self, path: Path, key: str) -> None:
        self.path = path
        self._header = {"isitright-run-cache": FORMAT, "host": key}
        self._runs: dict[str, RunResult] = {}
        self._lock = threading.Lock()
        self.restored = self._load()

    def _load(self) -> int:
        """Read the file back; a different host configuration or a torn last line is dropped."""
        kept: list[str] = []
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []
        if lines and _parse(lines[0]) == self._header:
            for line in lines[1:]:
                try:
                    entry = json.loads(line)
                    self._runs[entry["key"]] = RunResult(**entry["run"])
                except (ValueError, KeyError, TypeError):
                    continue
                kept.append(line)
        # Rewrite so that new records never join onto a half-written line.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join([json.dumps(self._header), *kept]) + "\n", encoding="utf-8")
        return len(self._runs)

    def get(self, key: str) -> RunResult | None:
        with self._lock:
            return self._runs.get(key)

    def put(self, key: str, run: RunResult) -> None:
        if run.status in NOT_STORED:
            return
        try:
            line = json.dumps({"key": key, "run": asdict(run)})
        except TypeError:  # an answer that is not plain JSON is simply not stored
            return
        with self._lock:
            self._runs[key] = run
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())


def discard_file(path: Path) -> None:
    """Delete a cache file (and its directory when empty): the results are saved elsewhere."""
    path.unlink(missing_ok=True)
    with suppress(OSError):
        path.parent.rmdir()


def _parse(line: str) -> object:
    try:
        return json.loads(line)
    except ValueError:
        return None
