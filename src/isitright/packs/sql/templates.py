"""Query templates: fill ``<NAME>`` and ``{{ NAME }}`` placeholders before parsing.

Warehouse queries are often templates (``WHERE ds = '<LATEST_DS>'``, Airflow's ``{{ ds }}``). The
values are declared (``--param NAME=VALUE``), filled into both queries identically before they are
parsed, and recorded in the report. No template logic: a placeholder is a name, nothing else. An
unfilled placeholder is an error that names it. ``<NAME>`` is a placeholder only when NAME is
upper case, so comparisons such as ``a<b`` or ``x <= Y`` are untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from isitright.packs.sql.errors import SqlInputError

_ANGLE = re.compile(r"<([A-Z][A-Z0-9_]*)>")
_BRACES = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class FilledTemplate:
    reference: str
    candidate: str
    params: dict[str, str] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    original_reference: str = ""
    original_candidate: str = ""

    @property
    def filled(self) -> bool:
        return bool(self.used)

    def record(self) -> dict[str, object]:
        return {
            "params": dict(self.params),
            "used": list(self.used),
            "unused": list(self.unused),
            "original_reference_sql": self.original_reference,
            "original_candidate_sql": self.original_candidate,
        }


def parse_params(items: list[str]) -> dict[str, str]:
    """``NAME=VALUE`` strings (the command line form) as a mapping."""
    out: dict[str, str] = {}
    for item in items:
        name, separator, value = item.partition("=")
        if not separator:
            raise SqlInputError(f"parameter {item!r} must look like NAME=VALUE")
        out[name.strip()] = value
    return out


def check_params(params: dict[str, str]) -> None:
    for name, value in params.items():
        if not _NAME.match(name):
            raise SqlInputError(f"parameter name {name!r} must be letters, digits and underscore")
        if ";" in value or any(ord(c) < 32 for c in value):
            raise SqlInputError(f"parameter {name} has a semicolon or control character")


def _names(sql: str) -> list[str]:
    return [m.group(1) for m in _ANGLE.finditer(sql)] + [m.group(1) for m in _BRACES.finditer(sql)]


def fill_templates(reference: str, candidate: str, params: dict[str, str]) -> FilledTemplate:
    """Both queries with every placeholder replaced, or `SqlInputError` naming one that is not."""
    check_params(params)
    used: list[str] = []

    def substitute(sql: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in params:
                raise SqlInputError(f"UNFILLED_PLACEHOLDER: {match.group(0)} has no --param {name}")
            if name not in used:
                used.append(name)
            return params[name]

        return _BRACES.sub(replace, _ANGLE.sub(replace, sql))

    filled_reference, filled_candidate = substitute(reference), substitute(candidate)
    return FilledTemplate(
        reference=filled_reference,
        candidate=filled_candidate,
        params=dict(params),
        used=used,
        unused=[n for n in params if n not in used],
        original_reference=reference,
        original_candidate=candidate,
    )
