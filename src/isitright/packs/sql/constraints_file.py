"""Load a domain-constraints document: JSON Schema (Draft 2020-12) in YAML or JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]


class ConstraintInputError(ValueError):
    """Raised when a constraints document cannot be safely interpreted."""


def load_constraint_schema(path: Path | None) -> dict[str, Any] | None:
    """Load a YAML/JSON document and verify it is JSON Schema Draft 2020-12."""
    if path is None:
        return None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConstraintInputError(f"could not read constraints document: {error}") from error
    if not isinstance(value, dict):
        raise ConstraintInputError("constraints document must contain a JSON Schema object")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as error:
        raise ConstraintInputError(f"invalid JSON Schema constraints: {error.message}") from error
    return value
