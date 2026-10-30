"""Subjects: what is under test, and the record of one run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

RunStatus = Literal["COMPLETED", "SUBJECT_ERROR", "TIMEOUT"]


class SubjectKind(StrEnum):
    ARTIFACT = "ARTIFACT"
    """A static program the agent produced (SQL, pandas): one deterministic run."""
    FROZEN_ARTIFACT = "FROZEN_ARTIFACT"
    """A program extracted from one live run, then tested across worlds."""
    AGENT = "AGENT"
    """The live agent in the mutated world: several runs, possibly different each time."""


@dataclass(frozen=True)
class Cost:
    """What a run used. ``money`` is in the unit the adapter reports (simulated or real)."""

    input_tokens: int = 0
    output_tokens: int = 0
    money: float = 0.0
    seconds: float = 0.0

    def __add__(self, other: Cost) -> Cost:
        return Cost(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.money + other.money,
            self.seconds + other.seconds,
        )


@dataclass(frozen=True)
class Task:
    id: str
    text: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    status: RunStatus = "COMPLETED"
    output: Any = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    final_state: Any = None
    cost: Cost = field(default_factory=Cost)
    details: dict[str, Any] = field(default_factory=dict)
    run_dir: str | None = None


class Subject(Protocol):
    kind: SubjectKind

    def run(self, handle: Any, task: Task) -> RunRecord: ...
