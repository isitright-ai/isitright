"""Oracles: what is right in a changed world, and when they cannot say."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from isitright.core.mutations import World
from isitright.core.subjects import RunRecord, Task


class OracleKind(StrEnum):
    REFERENCE_PROGRAM = "REFERENCE_PROGRAM"
    INVARIANT = "INVARIANT"
    RELATIONAL = "RELATIONAL"
    CONSTRUCTIVE = "CONSTRUCTIVE"
    JUDGE = "JUDGE"


class Outcome(StrEnum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    CANNOT_JUDGE = "CANNOT_JUDGE"


class Role(StrEnum):
    BASELINE = "baseline"
    CONTROL = "control"
    """The reference procedure says to act."""
    TRAP = "trap"
    """The reference procedure says to do nothing."""
    UNJUDGEABLE = "unjudgeable"


@dataclass
class Judgement:
    outcome: Outcome
    messages: list[str] = field(default_factory=list)
    violations: list[tuple[str, str]] = field(default_factory=list)
    """(oracle name, message) for each violated invariant."""


class Oracle(Protocol):
    kind: OracleKind
    name: str
    description: str

    def judge(self, task: Task, before: World, run: RunRecord) -> Judgement: ...


class RoleOracle(Protocol):
    """An oracle that can also say, for any world, whether acting is right."""

    def role(self, task: Task, world: World) -> tuple[Role, str]: ...


def controls_status(roles_and_outcomes: list[tuple[Role, list[Outcome]]]) -> tuple[str, str]:
    """DISCRIMINATING when the agent reached the expected behavior in every control it ran.

    A control never reached in any run means a refuse-everything agent cannot be told from a
    careful one: NOT_DISCRIMINATING. No control with a completed run: NOT_APPLICABLE.
    """
    controls = [o for role, o in roles_and_outcomes if role is Role.CONTROL and o]
    if not controls:
        return "NOT_APPLICABLE", "no control world completed a run"
    silent = sum(1 for outcomes in controls if Outcome.MET not in outcomes)
    if silent:
        return (
            "NOT_DISCRIMINATING",
            f"the expected behavior was never reached in {silent} of {len(controls)} "
            "control worlds",
        )
    return (
        "DISCRIMINATING",
        f"the expected behavior was reached in all {len(controls)} control worlds",
    )
