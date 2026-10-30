"""Engine-independent JSON Schema validation of data-only SQL snapshots."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]


def domain_errors(snapshot: dict[str, Any], schema: dict[str, Any]) -> list[ValidationError]:
    """Return deterministic violations; engine validity is checked separately."""
    return sorted(
        Draft202012Validator(schema).iter_errors(snapshot),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
