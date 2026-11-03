"""Comparing the answers of two programs under an explicit, recorded policy.

Answers are plain JSON: numbers, text, lists, mappings of named answers (the benchmark's
``@name[value]`` form), and frames (``{"__frame__": ...}``). A narrative answer is
``CANNOT_JUDGE``. Every comparison carries the policy that decided it, and the policy goes into
the report with its basis.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from isitright.core.compare import Comparison, NumericComparator, TextComparator

_NAMED = re.compile(r"@\s*([A-Za-z0-9_\- ]+?)\s*\[(.*?)\]", re.S)
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_DECIMALS = re.compile(r"(?:to|by)\s+(?:the\s+)?(?:nearest\s+)?(\w+)\s+decimal", re.I)
_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


class CannotJudge(Exception):
    """The answer is narrative or has a shape the policy does not cover."""


def decimals_in(text: str) -> int | None:
    """The decimals a question asks for ("rounded to two decimal places"): the fewest it names,
    so that two programs rounding a boundary value differently are not told apart."""
    found = []
    for match in _DECIMALS.finditer(text):
        word = match.group(1).lower()
        if word.isdigit():
            found.append(int(word))
        elif word in _WORDS:
            found.append(_WORDS[word])
    found.extend(int(m.group(1)) for m in re.finditer(r"(\d+)\s+decimal", text, re.I))
    return min(found) if found else None


def normal_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def to_value(raw: Any) -> Any:
    """A scalar from an answer cell: numeric text becomes a float; other text is stripped."""
    if isinstance(raw, str) and raw.strip().lower() in {"nan", "inf", "-inf"}:
        return float(raw.strip())
    if isinstance(raw, str):
        text = (
            raw.strip().rstrip("%").replace(",", "")
            if _NUMBER.match(raw.strip().rstrip("%").replace(",", ""))
            else raw.strip()
        )
        return float(text) if _NUMBER.match(text) else text
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float):
        return float(raw)
    return raw


def named_answers(text: str) -> dict[str, Any] | None:
    """The ``@name[value]`` pairs of a text answer, or None if it has none."""
    pairs = _NAMED.findall(text)
    if not pairs:
        return None
    return {normal_name(name): to_value(value) for name, value in pairs}


def normalize_answer(raw: Any) -> Any:
    """The comparable form of a program's answer."""
    if isinstance(raw, str):
        named = named_answers(raw)
        return named if named is not None else to_value(raw)
    if isinstance(raw, dict):
        if "__frame__" in raw:
            return raw
        if "__other__" in raw:
            raise CannotJudge(f"the answer is not data: {raw['__other__']}")
        if set(raw) == {"__float__"}:  # a non-finite float the runner could not put in JSON
            return float(raw["__float__"])
        if set(raw) == {"type", "value"}:  # the PandasAI result convention
            return normalize_answer(raw["value"])
        return {normal_name(str(k)): normalize_answer(v) for k, v in raw.items()}
    if isinstance(raw, list | tuple):
        return [normalize_answer(v) for v in raw]
    return to_value(raw)


@dataclass(frozen=True)
class AnswerPolicy:
    """How two answers are compared: the numeric tolerance and its basis, and how text matches."""

    abs_tol: float = 1e-9
    rel_tol: float = 1e-9
    basis: str = "default: floating-point noise"
    text: str = "normalized"
    frame: FramePolicy | None = None

    @staticmethod
    def for_question(text: str) -> AnswerPolicy:
        digits = decimals_in(text)
        if digits is None:
            return AnswerPolicy()
        return AnswerPolicy(
            abs_tol=10.0**-digits * (1 + 1e-9),
            rel_tol=0.0,
            basis=f"question asks for {digits} decimal places: one unit in the last place",
        )

    def describe(self) -> dict[str, Any]:
        out = {
            "kind": "structured_answer",
            "numbers": self.numeric().describe(),
            "text": self.text,
        }
        if self.frame is not None:
            out["frame"] = self.frame.describe()
        return out

    def numeric(self) -> NumericComparator:
        return NumericComparator(self.abs_tol, self.rel_tol, self.basis)


@dataclass(frozen=True)
class FramePolicy:
    index: str = "ignore"
    dtype: str = "kind"
    column_order: str = "strict"
    row_order: str = "strict"

    def describe(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "dtype": self.dtype,
            "column_order": self.column_order,
            "row_order": self.row_order,
        }


def _kind(dtype: str) -> str:
    if dtype.startswith(("int", "uint", "Int", "UInt")):
        return "int"
    if dtype.startswith(("float", "Float")):
        return "float"
    if dtype.startswith("bool") or dtype == "boolean":
        return "bool"
    return "text"


@dataclass
class DataComparator:
    """Compares two normalized answers; ``compare`` takes raw answers from the host."""

    policy: AnswerPolicy = field(default_factory=AnswerPolicy)

    def describe(self) -> dict[str, Any]:
        return self.policy.describe()

    def compare(self, expected: Any, actual: Any) -> Comparison:
        try:
            left, right = normalize_answer(expected), normalize_answer(actual)
            difference = self._differs(left, right, "answer")
        except CannotJudge as error:
            return Comparison(False, str(error), inconclusive=True)
        return Comparison(difference is None, difference)

    def _differs(self, left: Any, right: Any, where: str) -> str | None:
        if isinstance(left, dict) and "__frame__" in left:
            if not (isinstance(right, dict) and "__frame__" in right):
                return f"{where}: expected a table, got {_shape(right)}"
            return self._frames(left["__frame__"], right["__frame__"])
        if isinstance(left, dict):
            if not isinstance(right, dict) and len(left) == 1:
                # a bare value stands for a task with a single named answer
                return self._differs(next(iter(left.values())), right, where)
            if not isinstance(right, dict):
                return f"{where}: expected named answers {sorted(left)}, got {_shape(right)}"
            if set(left) != set(right):
                return f"{where}: names differ: expected {sorted(left)}, got {sorted(right)}"
            for name in sorted(left):
                inner = self._differs(left[name], right[name], f"{where}[{name}]")
                if inner:
                    return inner
            return None
        if isinstance(left, list):
            if isinstance(right, str):  # "a, b" for ["a", "b"]; "" for []
                right = [to_value(item) for item in right.split(",") if item.strip()]
            if not isinstance(right, list) or len(left) != len(right):
                return f"{where}: expected {len(left)} items, got {_shape(right)}"
            for position, (a, b) in enumerate(zip(left, right, strict=True)):
                inner = self._differs(a, b, f"{where}[{position}]")
                if inner:
                    return inner
            return None
        return self._scalars(left, right, where)

    def _scalars(self, left: Any, right: Any, where: str) -> str | None:
        if left is None or right is None:
            return None if left is right else f"{where}: expected {left!r}, got {right!r}"
        left_number = isinstance(left, float) and not isinstance(left, bool)
        right_number = isinstance(right, float) and not isinstance(right, bool)
        if left_number and right_number:
            outcome = self.policy.numeric().compare(left, right)
            return None if outcome.matches else f"{where}: {outcome.difference}"
        if left_number != right_number:
            return f"{where}: expected {left!r}, got {right!r}"
        outcome = TextComparator(self.policy.text).compare(left, right)
        return None if outcome.matches else f"{where}: {outcome.difference}"

    def _frames(self, left: dict[str, Any], right: dict[str, Any]) -> str | None:
        policy = self.policy.frame or FramePolicy()
        lcols, rcols = left["columns"], right["columns"]
        if policy.column_order == "ignore":
            if sorted(lcols) != sorted(rcols):
                return f"columns differ: expected {lcols}, got {rcols}"
        elif lcols != rcols:
            return f"columns differ: expected {lcols}, got {rcols}"
        order = [rcols.index(c) for c in lcols]
        lrows = [list(r) for r in left["data"]]
        rrows = [[r[i] for i in order] for r in right["data"]]
        if len(lrows) != len(rrows):
            return f"row count differs: expected {len(lrows)}, got {len(rrows)}"
        if policy.dtype != "ignore":
            rdt = [right["dtypes"][i] for i in order]
            for name, a, b in zip(lcols, left["dtypes"], rdt, strict=True):
                same = a == b if policy.dtype == "strict" else _kind(a) == _kind(b)
                if not same:
                    return f"dtype of {name!r} differs: expected {a}, got {b}"
        if policy.index == "strict" and left["index"] != right["index"]:
            return "index differs"
        if policy.row_order == "ignore":
            lrows.sort(key=repr)
            rrows.sort(key=repr)
        for position, (a, b) in enumerate(zip(lrows, rrows, strict=True)):
            for name, x, y in zip(lcols, a, b, strict=True):
                inner = self._scalars(to_value(x), to_value(y), f"row {position} column {name!r}")
                if inner:
                    return inner
        return None


def _shape(value: Any) -> str:
    if isinstance(value, dict):
        return "a table" if "__frame__" in value else f"named answers {sorted(value)}"
    return repr(value)[:80]


def is_finite_number(value: Any) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def undefined_answer(raw: Any) -> bool:
    """Whether an answer holds NaN or infinity: the reference has no defined answer for the world
    (an empty column's mean), so there is nothing to compare a program with."""
    try:
        value = normalize_answer(raw)
    except CannotJudge:
        return False
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float) and not math.isfinite(item):
            return True
        if isinstance(item, dict) and "__frame__" not in item:
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False
