"""Generic mutation families over the entity model and the tool output schema."""

from __future__ import annotations

from isitright.core.families.json import JsonEdit
from isitright.core.families.other import PriorOperation, ResponseEdits, Timing
from isitright.core.families.state import (
    Boundary,
    CardinalityBoundary,
    Dangling,
    Duplicate,
    EdgeValue,
    Empty,
    KeyCollision,
    Missing,
    OutOfScopeExtreme,
    ReferenceSwap,
    Representation,
    ServiceParameter,
    Split,
    Temporal,
    Tie,
    UnitsScale,
)
from isitright.core.mutations import Mutator


def default_mutators(insert_variants: bool = False) -> list[Mutator]:
    """The built-in families, in the order the search visits them.

    ``insert_variants`` makes Boundary and Missing add a changed copy of an entity instead of
    changing it in place (the shape SQL perturbations take: the original rows stay).
    """
    return [
        Boundary(insert=insert_variants),
        Missing(insert=insert_variants),
        KeyCollision(),
        Duplicate(),
        Tie(),
        Empty(),
        Dangling(),
        ReferenceSwap(),
        CardinalityBoundary(),
        PriorOperation(),
        Split(),
        Representation(),
        OutOfScopeExtreme(),
        Temporal(),
        UnitsScale(),
        JsonEdit(),
        ServiceParameter(),
        ResponseEdits(),
        Timing(),
        EdgeValue(insert=insert_variants),
    ]


__all__ = ["default_mutators"]
