"""Tool-call trace recording for the MCP host."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    """One tool call served by the host."""

    index: int
    name: str
    arguments: dict[str, Any]
    result: str
    is_error: bool


class TraceRecorder:
    """Thread-safe, append-only log of the calls a host served.

    ``on_record`` is called with each event as it is recorded, for example to persist it from a
    host that runs in its own process.
    """

    def __init__(self, on_record: Callable[[TraceEvent], None] | None = None) -> None:
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()
        self._on_record = on_record

    def record(self, name: str, arguments: dict[str, Any], result: str, *, is_error: bool) -> None:
        with self._lock:
            event = TraceEvent(len(self._events), name, dict(arguments), result, is_error)
            self._events.append(event)
            if self._on_record is not None:
                self._on_record(event)

    @property
    def events(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._events)

    def to_json(self) -> list[dict[str, Any]]:
        return [asdict(event) for event in self.events]
