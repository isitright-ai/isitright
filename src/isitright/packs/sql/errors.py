"""Errors of the SQL pack."""

from __future__ import annotations


class SqlInputError(ValueError):
    """The input is outside the explicitly supported SQL subset."""


class StateRejected(ValueError):
    """A proposed state failed the engine's own schema or type validation while loading."""
