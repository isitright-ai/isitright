"""Hosts: make a world available to a subject, and say how faithfully."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from isitright.core.mutations import World
from isitright.core.spec import WorldSpec


class Fidelity(StrEnum):
    NATIVE_ISOLATED = "NATIVE_ISOLATED"
    NATIVE_INLINE = "NATIVE_INLINE"
    EMULATED = "EMULATED"
    SIMULATED = "SIMULATED"
    GENERATED = "GENERATED"
    REPLAY_ONLY = "REPLAY_ONLY"


@dataclass(frozen=True)
class FoundOn:
    """Where a result was computed, and where it was confirmed, if anywhere."""

    found_on: Fidelity
    verified_on: Fidelity | None = None
    engine: str | None = None


class Host(Protocol):
    fidelity: Fidelity

    def prepare(self, spec: WorldSpec, world: World) -> AbstractContextManager[Any]: ...
