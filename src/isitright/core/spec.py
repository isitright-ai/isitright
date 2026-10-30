"""World spec: what states can exist, plus the tools and parameters of a service."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.constraints import (
    Constraint,
    PythonConstraint,
    Validity,
    check_constraints,
    check_paths,
    constraints_to_json,
)
from isitright.core.entities import EntitySchema, ModelError
from isitright.core.world import Atom, State


class ToolSpec(BaseModel):
    """One tool of a service. ``exposes`` lists the entity fields a call can show the agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    writes: bool = False
    exposes: list[str] = Field(default_factory=list)
    """Paths such as ``orders.status`` that appear in this tool's output."""
    list_field: str | None = None
    """For a tool that returns a list under one key (``orders``): response edits may reorder it."""
    nested_lists: list[str] = Field(default_factory=list)
    """Output keys holding lists (``payments``) that a response edit may drop."""


class ParamSpec(BaseModel):
    """A service parameter (a page cap, a sort order) that the pack's handlers honor.

    Generic mutators set its value; ``values`` lists the values worth trying besides the default.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "json"
    default: Any = None
    values: list[Any] = Field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class Operation:
    """One of the service's own write operations, used by the prior-operation family.

    ``options(state)`` yields argument sets; ``apply(state, arguments)`` returns the new state, or
    None when the operation does not apply. The result is reachable by construction.
    """

    name: str
    options: Callable[[State], Iterator[dict[str, Any]]]
    apply: Callable[[State, dict[str, Any]], State | None]
    touches: Callable[[dict[str, Any]], list[Atom]] = lambda _: []


@dataclass
class WorldSpec:
    id: str
    schema: EntitySchema
    constraints: list[Constraint] = field(default_factory=list)
    python_constraints: list[PythonConstraint] = field(default_factory=list)
    params: list[ParamSpec] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    policy: str | None = None

    def __post_init__(self) -> None:
        try:
            check_paths(self.schema, self.constraints)
        except ModelError as error:
            raise ModelError(f"world spec {self.id!r}: {error}") from error

    def validate(self, state: State) -> Validity:
        return check_constraints(self.schema, self.constraints, self.python_constraints, state)

    def exposed_paths(self) -> set[str]:
        return {p for tool in self.tools for p in tool.exposes}

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema": self.schema.model_dump(mode="json"),
            "constraints": constraints_to_json(self.constraints),
            "check_only_constraints": [c.name for c in self.python_constraints],
            "params": [p.model_dump(mode="json") for p in self.params],
            "tools": [t.model_dump(mode="json") for t in self.tools],
        }
