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
RECORDS = "__records__"
"""Key of an answer that is a list of groups, such as one block of answers per continent."""
_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


class CannotJudge(Exception):
    """The answer is narrative or has a shape the policy does not cover."""


def decimals_named(text: str) -> list[int]:
    """Every distinct number of decimals a text names ("rounded to two decimal places"), sorted."""
    found = []
    for match in _DECIMALS.finditer(text):
        word = match.group(1).lower()
        if word.isdigit():
            found.append(int(word))
        elif word in _WORDS:
            found.append(_WORDS[word])
    found.extend(int(m.group(1)) for m in re.finditer(r"(\d+)\s+decimal", text, re.I))
    return sorted(set(found))


def decimals_in(text: str) -> int | None:
    """The decimals a question asks for: the fewest it names, so that two programs rounding a
    boundary value differently are not told apart."""
    found = decimals_named(text)
    return found[0] if found else None


_DECIMAL_MENTION = re.compile(r"(?:(?:to|by)\s+(?:the\s+)?(?:nearest\s+)?)?(\w+)\s+decimal", re.I)


def _decimals_in_order(text: str) -> list[int]:
    """The decimals a text names, in the order it names them and with repeats."""
    found = []
    for match in _DECIMAL_MENTION.finditer(text):
        word = match.group(1).lower()
        if word.isdigit():
            found.append(int(word))
        elif word in _WORDS:
            found.append(_WORDS[word])
    return found


def decimals_resolution(text: str) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Decimals stated for named answers: ``(resolved, undetermined)``.

    The clause from an answer's name to the next answer's name or the end of the sentence names
    one precision: that answer's. A sentence ending in "respectively" that lists as many answers
    as precisions ("r_value and p_value are rounded to two decimal places and four decimal places
    respectively") gives them in order. An answer whose clause names several precisions that
    neither rule separates is ``undetermined``: the precisions it names are returned so the caller
    can state that the question does not settle it (the 0.9 review: falling back to the coarsest
    precision accepted two p-values that differ at the fourth decimal). Names come from the
    ``@name[...]`` template; the template itself is skipped."""
    names = {normal_name(n): n for n, _ in _NAMED.findall(text)}
    if len(names) < 2:
        return {}, {}
    plain = _NAMED.sub(" ", text)
    spots = sorted(
        (match.start(), key)
        for key, name in names.items()
        for match in re.finditer(rf"(?<![\w@]){re.escape(name.strip())}(?!\w)", plain)
    )
    out: dict[str, int] = {}
    named: dict[str, list[int]] = {}
    for index, (start, key) in enumerate(spots):
        end = spots[index + 1][0] if index + 1 < len(spots) else len(plain)
        clause = plain[start:end]
        stop = re.search(r"\.(\s|$)", clause)
        digits = decimals_named(clause[: stop.start()] if stop else clause)
        if len(digits) == 1 and key not in out:
            out[key] = digits[0]
        elif len(digits) > 1:
            named.setdefault(key, digits)
    for sentence in re.split(r"\.(?:\s|$)", plain):
        if "respectively" not in sentence.lower():
            continue
        listed: list[str] = []
        for _, key in sorted(
            (m.start(), key)
            for key, name in names.items()
            for m in re.finditer(rf"(?<![\w@]){re.escape(name.strip())}(?!\w)", sentence)
        ):
            if key not in listed:
                listed.append(key)
        in_order = _decimals_in_order(sentence)
        if len(listed) == len(in_order) and len(listed) > 1:
            for key, places in zip(listed, in_order, strict=True):
                out[key] = places
                named.pop(key, None)
        elif len(listed) > 1 and len(set(in_order)) > 1:
            for key in listed:  # "respectively" without a one-to-one pairing: none is settled
                out.pop(key, None)
                named[key] = sorted(set(in_order))
    undetermined = {key: digits for key, digits in named.items() if key not in out}
    return out, undetermined


def decimals_per_answer(text: str) -> dict[str, int]:
    """The precisions the text settles for named answers (see ``decimals_resolution``)."""
    return decimals_resolution(text)[0]


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
        return float(text) if _NUMBER.match(text) else _unquote(text)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float):
        return float(raw)
    return raw


def _unquote(text: str) -> str:
    """The text without a pair of quotes around it (agents print ``'Kuwait'``).

    Only a single quoted value is unwrapped: ``'a', 'b'`` is a list, not one value in quotes.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" and text[0] not in text[1:-1]:
        return text[1:-1].strip()
    return text


def named_answers(text: str) -> dict[str, Any] | None:
    """The ``@name[value]`` pairs of a text answer, or None if it has none.

    When the first name comes round again the answer is a list of groups (one block per continent,
    say) and is returned as ``{RECORDS: [{name: value, ...}, ...]}``.
    """
    pairs = [(normal_name(name), to_value(value)) for name, value in _NAMED.findall(text)]
    if not pairs:
        return None
    first = pairs[0][0]
    if [name for name, _ in pairs].count(first) < 2:
        return dict(pairs)
    records: list[dict[str, Any]] = []
    for name, value in pairs:
        if name == first:
            records.append({})
        records[-1][name] = value
    return {RECORDS: records}


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
        items = [normalize_answer(v) for v in raw]
        if items and all(
            isinstance(i, dict) and "__frame__" not in i and RECORDS not in i for i in items
        ):
            return {RECORDS: items}  # a list of groups, as the text form gives
        return items
    return to_value(raw)


@dataclass(frozen=True)
class AnswerPolicy:
    """How two answers are compared: the numeric tolerance and its basis, and how text matches."""

    abs_tol: float = 1e-9
    rel_tol: float = 1e-9
    basis: str = "default: floating-point noise"
    text: str = "normalized"
    frame: FramePolicy | None = None
    ulps: int = 0
    per_answer: dict[str, int] = field(default_factory=dict)
    """Decimals stated for one named answer (normalized name); the others use ``abs_tol``."""
    undetermined: dict[str, list[int]] = field(default_factory=dict)
    """Answers whose clause names several precisions that the text does not separate. They are
    compared at the finest precision named and reported as undetermined, never at the task's
    coarser one."""

    @staticmethod
    def for_question(text: str) -> AnswerPolicy:
        digits = decimals_in(text)
        if digits is None:
            return AnswerPolicy()
        # One unit in the last place, plus 2 ulps for the rounding of the difference itself: near
        # 2e6 the difference of two numbers one unit (0.01) apart is off by a few 1e-10, so a
        # rounding that differs by one unit at a tie (2243963.30 against 2243963.31) would
        # otherwise count as a disagreement. (0.6 to 0.8 used rel_tol 1e-15 and abs_tol x 1+1e-9,
        # 4.5 to 9 ulps.) Answers whose own clause names finer decimals get their own unit.
        resolved, undetermined = decimals_resolution(text)
        per_answer = {name: d for name, d in resolved.items() if d != digits}
        for name, named in undetermined.items():
            if max(named) != digits:
                per_answer[name] = max(named)
        return AnswerPolicy(
            abs_tol=10.0**-digits,
            rel_tol=0.0,
            ulps=2,
            basis=f"question asks for {digits} decimal places: one unit in the last place",
            per_answer=per_answer,
            undetermined=undetermined,
        )

    def describe(self) -> dict[str, Any]:
        out = {
            "kind": "structured_answer",
            "numbers": self.numeric().describe(),
            "text": self.text,
        }
        if self.per_answer:
            out["numbers_per_answer"] = {
                name: self.numeric(name).describe() for name in sorted(self.per_answer)
            }
        if self.undetermined:
            out["precision_undetermined"] = {
                name: {
                    "named": digits,
                    "used": max(digits),
                    "note": "the question names several precisions for this answer that its text "
                    "does not separate; the finest is used, so a difference at a coarser one is "
                    "reported",
                }
                for name, digits in sorted(self.undetermined.items())
            }
        if self.frame is not None:
            out["frame"] = self.frame.describe()
        return out

    def numeric(self, answer: str | None = None) -> NumericComparator:
        """The comparator for a named answer (its own decimals if stated), else the task's."""
        if answer is not None and answer in self.per_answer:
            digits = self.per_answer[answer]
            basis = f"the question asks for {digits} decimal places for {answer}"
            if answer in self.undetermined:
                basis = (
                    f"the question names {sorted(self.undetermined[answer])} decimal places for "
                    f"{answer} without saying which applies: the finest ({digits}) is used"
                )
            return NumericComparator(10.0**-digits, 0.0, basis, self.ulps)
        return NumericComparator(self.abs_tol, self.rel_tol, self.basis, self.ulps)


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

    def _differs(self, left: Any, right: Any, where: str, answer: str | None = None) -> str | None:
        if isinstance(left, dict) and "__frame__" in left:
            if not (isinstance(right, dict) and "__frame__" in right):
                return f"{where}: expected a table, got {_shape(right)}"
            return self._frames(left["__frame__"], right["__frame__"])
        left_groups = isinstance(left, dict) and RECORDS in left
        right_groups = isinstance(right, dict) and RECORDS in right
        if left_groups or right_groups:
            if not left_groups:
                return f"{where}: expected a single answer, got groups of answers"
            if not right_groups:
                return f"{where}: expected groups of answers, got {_shape(right)}"
            return self._groups(left[RECORDS], right[RECORDS], where)
        if isinstance(left, dict):
            if not isinstance(right, dict) and len(left) == 1:
                # a bare value stands for a task with a single named answer
                name, value = next(iter(left.items()))
                return self._differs(value, right, where, name)
            if not isinstance(right, dict):
                return f"{where}: expected named answers {sorted(left)}, got {_shape(right)}"
            if set(left) != set(right):
                return f"{where}: names differ: expected {sorted(left)}, got {sorted(right)}"
            for name in sorted(left):
                inner = self._differs(left[name], right[name], f"{where}[{name}]", name)
                if inner:
                    return inner
            return None
        if isinstance(left, list):
            if isinstance(right, str):  # "a, b" or "['a', 'b']" for ["a", "b"]; "" for []
                inside = right.strip().removeprefix("[").removesuffix("]")
                right = [to_value(item) for item in inside.split(",") if item.strip()]
            if not isinstance(right, list) or len(left) != len(right):
                return f"{where}: expected {len(left)} items, got {_shape(right)}"
            if all(isinstance(item, str) for item in left + right):
                # a list of names (outlier countries) has no stated order: compare as multisets
                if sorted(x.casefold() for x in left) != sorted(x.casefold() for x in right):
                    return f"{where}: expected {sorted(left)}, got {sorted(right)}"
                return None
            for position, (a, b) in enumerate(zip(left, right, strict=True)):
                inner = self._differs(a, b, f"{where}[{position}]", answer)
                if inner:
                    return inner
            return None
        return self._scalars(left, right, where, answer)

    def _groups(self, left: list[Any], right: list[Any], where: str) -> str | None:
        """Groups of answers, matched by the value of their first answer, so their order is free."""
        if len(left) != len(right):
            return f"{where}: expected {len(left)} groups, got {len(right)}"
        if not left:
            return None
        key = next(iter(left[0]))

        def label(group: dict[str, Any]) -> str:
            return str(group.get(key, "")).casefold()

        if len({label(g) for g in left}) == len(left) and len({label(g) for g in right}) == len(
            right
        ):
            by_label = {label(g): g for g in right}
            matched = []
            for group in left:
                other = by_label.get(label(group))
                if other is None:
                    return f"{where}: the answer has no group {group.get(key)!r}"
                matched.append((label(group), group, other))
        else:  # the first answer does not tell the groups apart: compare in order
            matched = [(str(i), a, b) for i, (a, b) in enumerate(zip(left, right, strict=True))]
        for name, a, b in matched:
            inner = self._differs(a, b, f"{where}[{name}]")
            if inner:
                return inner
        return None

    def _scalars(self, left: Any, right: Any, where: str, answer: str | None = None) -> str | None:
        if left is None or right is None:
            return None if left is right else f"{where}: expected {left!r}, got {right!r}"
        left_number = isinstance(left, float) and not isinstance(left, bool)
        right_number = isinstance(right, float) and not isinstance(right, bool)
        if left_number and right_number:
            outcome = self.policy.numeric(answer).compare(left, right)
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
