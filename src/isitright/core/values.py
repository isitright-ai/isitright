"""Value strategies inside families: edge values for a field, drawn with Hypothesis.

The core owns the search and keeps harvested literals as small finite sets that it enumerates.
Hypothesis supplies the other half: edge cases of a type (zero, negative, huge and tiny floats;
empty, padded and non-ASCII text) that nobody wrote down. Examples are found with `find` and a
derandomized profile, so the same inputs give the same values on every run.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from functools import cache
from typing import Any

from hypothesis import HealthCheck, Phase, settings
from hypothesis import find as hypothesis_find
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

from isitright.core.constraints import Domain

_PROFILE = settings(
    max_examples=300,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    phases=[Phase.generate, Phase.shrink],
)
_FLOATS = st.floats(allow_nan=False, allow_infinity=False, width=32)
_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=0, max_size=8)
_INTS = st.integers(min_value=-(2**31) + 1, max_value=2**31 - 1)

_FLOAT_CASES: tuple[Callable[[float], bool], ...] = (
    lambda x: x == 0.0,
    lambda x: x < 0,
    lambda x: abs(x) >= 1e6,
    lambda x: 0 < abs(x) < 1e-6,
)
_TEXT_CASES: tuple[Callable[[str], bool], ...] = (
    lambda s: s == "",
    lambda s: s != s.strip() and s.strip() != "",
    lambda s: not s.isascii(),
    lambda s: "'" in s,
)
_INT_CASES: tuple[Callable[[int], bool], ...] = (
    lambda n: n == 0,
    lambda n: n < 0,
    lambda n: abs(n) >= 2**24,
)


def _find(strategy: st.SearchStrategy[Any], condition: Callable[[Any], bool]) -> Any | None:
    try:
        return hypothesis_find(strategy, condition, settings=_PROFILE)
    except NoSuchExample:  # pragma: no cover - every case above is satisfiable
        return None


@cache
def _edges(kind: str) -> tuple[Any, ...]:
    if kind == "float":
        found = [_find(_FLOATS, c) for c in _FLOAT_CASES]
    elif kind == "text":
        found = [_find(_TEXT, c) for c in _TEXT_CASES]
    elif kind == "int":
        found = [_find(_INTS, c) for c in _INT_CASES]
    else:
        return ()
    values: list[Any] = []
    for value in found:
        if value is not None and value not in values:
            values.append(value)
    return tuple(values)


def edge_values(kind: str, domain: Domain | None = None) -> list[Any]:
    """Edge cases for a field type that a declared domain allows.

    ``kind`` is a core field type (``int``, ``float``, ``text``); other types have no edges here.
    """
    key = {"decimal": "float", "float": "float", "int": "int", "text": "text"}.get(kind)
    if key is None:
        return []
    out = []
    for value in _edges(key):
        if key == "int":
            candidate: Any = int(value)
        else:
            candidate = float(value) if key == "float" else value
        if domain is not None and not _inside(candidate, domain):
            continue
        out.append(candidate)
    return out


def _inside(value: Any, domain: Domain) -> bool:
    if domain.values is not None:
        return value in domain.values
    if isinstance(value, str):
        return True
    if domain.minimum is not None and (
        value < domain.minimum or (domain.min_exclusive and value == domain.minimum)
    ):
        return False
    return not (
        domain.maximum is not None
        and (value > domain.maximum or (domain.max_exclusive and value == domain.maximum))
    )


class UnsupportedPattern(ValueError):
    """A regular expression that value generation cannot honor (reported, never guessed)."""


_UNSUPPORTED_CONSTRUCTS = (
    (re.compile(r"\(\?(?:=|!|<=|<!)"), "lookahead and lookbehind"),
    (re.compile(r"\(\?P=|(?<!\\)\\[1-9]"), "backreferences"),
    (re.compile(r"\(\?\("), "conditional groups"),
)


def unsupported_pattern(pattern: str) -> str | None:
    """Why a pattern cannot drive generation, or None when it can."""
    try:
        re.compile(pattern)
    except re.error as error:
        return f"does not compile: {error}"
    for construct, name in _UNSUPPORTED_CONSTRUCTS:
        if construct.search(pattern):
            return f"uses {name}, which value generation does not support"
    return None


def pattern_value(
    pattern: str,
    *,
    taken: Collection[Any] = (),
    domain: Domain | None = None,
) -> str:
    """The smallest string that fully matches ``pattern`` and is not in ``taken``.

    Deterministic: the same pattern and the same ``taken`` give the same value on every run
    (Hypothesis, derandomized, shrinks toward the simplest match, so successive calls with the
    values already used give ``AAA``, ``AAB``, ``AAC`` for ``^[A-Z]{3}$``). A declared domain with
    a closed set of values narrows the matches to that set. Raises `UnsupportedPattern` for a
    construct that is not supported, and when no such value exists.
    """
    reason = unsupported_pattern(pattern)
    if reason is not None:
        raise UnsupportedPattern(f"pattern {pattern!r} {reason}")
    used = set(taken)
    found = _find(
        st.from_regex(pattern, fullmatch=True),
        lambda s: s not in used and (domain is None or _inside(s, domain)),
    )
    if found is None:
        raise UnsupportedPattern(f"pattern {pattern!r} has no further value within the domain")
    return str(found)


def nth_pattern_value(pattern: str, ordinal: int, domain: Domain | None = None) -> str:
    """The ``ordinal``-th (from 1) value in `pattern_value` order."""
    taken: list[str] = []
    for _ in range(max(ordinal, 1)):
        taken.append(pattern_value(pattern, taken=taken, domain=domain))
    return taken[-1]
