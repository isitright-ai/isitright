"""Comparators: an explicit equivalence policy between an expected and an actual output."""

from __future__ import annotations

import math
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

    def describe(self) -> dict[str, Any]:
        """The policy as data, for the report's ``comparison_policy``."""
        ...


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

    def describe(self) -> dict[str, Any]:
        return {"kind": "json", "ignore_keys": sorted(self.ignore_keys)}


class NumericComparator:
    """Numbers within a declared tolerance: ``|a - b| <= abs_tol + rel_tol * |b|``.

    ``basis`` says where the tolerance comes from (for example "the question asks for two decimal
    places"), because a tolerance with no stated basis is a guess. Non-finite values match only
    when both are the same non-finite value.
    """

    def __init__(self, abs_tol: float, rel_tol: float, basis: str) -> None:
        if abs_tol < 0 or rel_tol < 0 or not basis:
            raise ValueError("tolerances must be non-negative and a basis must be stated")
        self.abs_tol, self.rel_tol, self.basis = abs_tol, rel_tol, basis

    def compare(self, expected: Any, actual: Any) -> Comparison:
        try:
            left, right = float(expected), float(actual)
        except (TypeError, ValueError):
            return Comparison(False, f"not numbers: {expected!r}, {actual!r}", inconclusive=True)
        if not (math.isfinite(left) and math.isfinite(right)):
            same = left == right or (math.isnan(left) and math.isnan(right))
            return Comparison(same, None if same else f"expected {left!r}, got {right!r}")
        if abs(left - right) <= self.abs_tol + self.rel_tol * abs(left):
            return Comparison(True)
        return Comparison(False, f"expected {left!r}, got {right!r} (tolerance: {self.basis})")

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "numeric",
            "abs_tol": self.abs_tol,
            "rel_tol": self.rel_tol,
            "basis": self.basis,
        }


class TextComparator:
    """Text equal exactly (``none``) or after trimming and case folding (``normalized``)."""

    def __init__(self, normalize: str = "normalized") -> None:
        if normalize not in {"none", "normalized"}:
            raise ValueError("normalize must be 'none' or 'normalized'")
        self.normalize = normalize

    def _form(self, value: Any) -> str:
        text = str(value)
        return text if self.normalize == "none" else " ".join(text.split()).casefold()

    def compare(self, expected: Any, actual: Any) -> Comparison:
        left, right = self._form(expected), self._form(actual)
        if left == right:
            return Comparison(True)
        return Comparison(False, f"expected {left!r}, got {right!r}")

    def describe(self) -> dict[str, Any]:
        return {"kind": "text", "normalize": self.normalize}
