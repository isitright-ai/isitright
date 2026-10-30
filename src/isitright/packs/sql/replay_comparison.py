"""Shared replay outcome check; each report supplies its comparison semantics."""

from __future__ import annotations

from collections.abc import Callable

from isitright.packs.sql.models import QueryResult


def reproduces_disagreement(
    reference: QueryResult,
    candidate: QueryResult,
    expected_reference: QueryResult,
    expected_candidate: QueryResult,
    *,
    matches: Callable[[QueryResult, QueryResult], bool],
) -> bool:
    """Replay succeeds only if both recorded outputs and the disagreement recur."""
    return (
        matches(reference, expected_reference)
        and matches(candidate, expected_candidate)
        and not matches(reference, candidate)
    )
