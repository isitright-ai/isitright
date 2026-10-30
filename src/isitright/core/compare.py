"""Comparators: an explicit equivalence policy between an expected and an actual output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Comparison:
    matches: bool
    difference: str | None = None
    inconclusive: bool = False
    """The policy could not decide (ordering ambiguity, nondeterminism): never a counterexample."""


class Comparator(Protocol):
    def compare(self, expected: Any, actual: Any) -> Comparison: ...


class JsonComparator:
    """Structural equality of JSON-compatible outputs, with optional key normalization."""

    def __init__(self, ignore_keys: frozenset[str] = frozenset()) -> None:
        self.ignore_keys = ignore_keys

    def compare(self, expected: Any, actual: Any) -> Comparison:
        left, right = self._strip(expected), self._strip(actual)
        if left == right:
            return Comparison(True)
        return Comparison(False, f"expected {left!r}, got {right!r}")

    def _strip(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._strip(v) for k, v in value.items() if k not in self.ignore_keys}
        if isinstance(value, list):
            return [self._strip(v) for v in value]
        return value
