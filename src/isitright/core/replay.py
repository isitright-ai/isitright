"""Replay artifacts: the concrete minimized world plus what a pack needs to rerun it.

Replay starts from the concrete world, never from a seed or a search choice sequence. The pack
supplies the function that rebuilds the world on its host and reproduces both outcomes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.world import sha256_text


class ReplayArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["isitright-replay"] = "isitright-replay"
    version: Literal["0.4", "0.5"] = "0.5"
    pack: str
    case_id: str
    world: dict[str, Any]
    host: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ReplayResult:
    reproduced: bool
    details: list[str] = field(default_factory=list)


def write_artifact(path: Path, artifact: ReplayArtifact) -> str:
    """Write the artifact deterministically and return its SHA-256."""
    text = json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)


def load_artifact(path: Path) -> ReplayArtifact:
    return ReplayArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def replay(
    artifact: ReplayArtifact, rerun: Callable[[ReplayArtifact], dict[str, Any]]
) -> ReplayResult:
    """Rerun and compare each expected entry with what the pack produced."""
    observed = rerun(artifact)
    problems = [
        f"{key}: expected {expected!r}, observed {observed.get(key)!r}"
        for key, expected in artifact.expected.items()
        if observed.get(key) != expected
    ]
    return ReplayResult(not problems, problems or ["every expected outcome reproduced"])
