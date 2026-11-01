"""Mutations: data transforms from one world to another, with a family, a description and atoms.

A mutation is data (edits, a response edit or a timing trigger), so it composes, minimizes,
serializes into a report and explains itself. A *mutator* proposes mutations given the spec, the
current world and the hints.

Three targets: ``state`` changes what is true, ``response`` changes what one tool call returns
(the state is unchanged; the mutation declares what is true underneath), and ``timing`` applies
state edits after a matching tool call.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from isitright.core.hints import Hints
from isitright.core.spec import WorldSpec
from isitright.core.world import Atom, State, canonical_json, sha256_text

Target = Literal["state", "response", "timing"]
PathToken = str | int


class _Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetField(_Edit):
    op: Literal["set"] = "set"
    collection: str
    key: Any
    path: list[PathToken]
    value: Any


class UnsetField(_Edit):
    op: Literal["unset"] = "unset"
    collection: str
    key: Any
    path: list[PathToken]


class AddEntity(_Edit):
    op: Literal["add"] = "add"
    collection: str
    entity: dict[str, Any]


class RemoveEntity(_Edit):
    op: Literal["remove"] = "remove"
    collection: str
    key: Any


class SetParam(_Edit):
    op: Literal["param"] = "param"
    name: str
    value: Any


Edit = Annotated[
    SetField | UnsetField | AddEntity | RemoveEntity | SetParam, Field(discriminator="op")
]
_EDITS = TypeAdapter(list[Edit])


class EditError(ValueError):
    """An edit does not apply to the state."""


def apply_edits(state: State, edits: Sequence[Edit]) -> State:
    """Apply edits in order to a copy of the state.

    Only the rows an edit changes are copied; the others are shared with ``state`` (rows are never
    edited in place), so the cost of a proposal does not grow with the size of the database.
    """
    data = {c: list(rows) for c, rows in state.collections.items()}
    owned: set[int] = set()  # rows copied for this call, which later edits may change in place
    params = dict(state.params)
    for edit in edits:
        if isinstance(edit, SetParam):
            params[edit.name] = copy.deepcopy(edit.value)
            continue
        rows = data.setdefault(edit.collection, [])
        key_name = state.keys[edit.collection]
        if isinstance(edit, AddEntity):
            if any(r.get(key_name) == edit.entity.get(key_name) for r in rows):
                raise EditError(f"{edit.collection} already has key {edit.entity.get(key_name)!r}")
            rows.append(copy.deepcopy(edit.entity))
            continue
        index = next((i for i, r in enumerate(rows) if r.get(key_name) == edit.key), None)
        if index is None:
            raise EditError(f"no {edit.collection}[{edit.key!r}] to edit")
        if isinstance(edit, RemoveEntity):
            del rows[index]
            continue
        if id(rows[index]) not in owned:
            rows[index] = copy.deepcopy(rows[index])
            owned.add(id(rows[index]))
        holder: Any = rows[index]
        for token in edit.path[:-1]:
            holder = holder[token]
        if isinstance(edit, SetField):
            holder[edit.path[-1]] = copy.deepcopy(edit.value)
        else:
            holder.pop(edit.path[-1], None)
    return State({c: tuple(rows) for c, rows in data.items()}, state.keys, params)


def edits_between(before: State, after: State) -> list[Edit]:
    """Edits that turn one state into another: removals, additions, field sets, parameters."""
    edits: list[Edit] = []
    for collection in sorted(set(before.collections) | set(after.collections)):
        name = before.keys[collection]
        old = {e[name]: e for e in before.entities(collection)}
        new = {e[name]: e for e in after.entities(collection)}
        edits.extend(RemoveEntity(collection=collection, key=k) for k in old if k not in new)
        edits.extend(
            AddEntity(collection=collection, entity=e) for k, e in new.items() if k not in old
        )
        for key, entity in new.items():
            if key in old and old[key] != entity:
                for field_name in sorted(set(old[key]) | set(entity)):
                    if old[key].get(field_name, _ABSENT) == entity.get(field_name, _ABSENT):
                        continue
                    if field_name in entity:
                        edits.append(
                            SetField(
                                collection=collection,
                                key=key,
                                path=[field_name],
                                value=entity[field_name],
                            )
                        )
                    else:
                        edits.append(UnsetField(collection=collection, key=key, path=[field_name]))
    for name, value in after.params.items():
        if before.params.get(name, _ABSENT) != value:
            edits.append(SetParam(name=name, value=value))
    return edits


_ABSENT = object()


def edits_to_json(edits: Sequence[Edit]) -> list[dict[str, Any]]:
    return list(_EDITS.dump_python(list(edits), mode="json"))


def edits_from_json(data: list[dict[str, Any]]) -> list[Edit]:
    return _EDITS.validate_python(data)


def touched_fields(edits: Sequence[Edit]) -> list[str]:
    """``collection.field`` paths an edit changes; an added or removed entity touches them all."""
    out: list[str] = []
    for edit in edits:
        if isinstance(edit, SetField | UnsetField):
            out.append(f"{edit.collection}.{edit.path[0]}")
        elif isinstance(edit, AddEntity):
            out.extend(f"{edit.collection}.{name}" for name in edit.entity)
        elif isinstance(edit, RemoveEntity):
            out.append(f"{edit.collection}.*")
    return out


class Trigger(BaseModel):
    """Fire after a successful call to ``tool`` whose arguments contain ``match``."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    match: dict[str, Any] = Field(default_factory=dict)

    def matches(self, tool: str, arguments: dict[str, Any]) -> bool:
        return tool == self.tool and all(arguments.get(k) == v for k, v in self.match.items())


class ResponseEdit(BaseModel):
    """An edit to what one tool returns. ``declares`` states what is true underneath."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    op: Literal["reorder", "drop_field", "empty_ack", "error"]
    field: str | None = None
    first_only: bool = False
    declares: str = ""


class Timer(BaseModel):
    """State edits that fire once, after a matching call."""

    model_config = ConfigDict(extra="forbid")

    name: str
    trigger: Trigger
    edits: list[Edit]
    record: dict[str, Any] | None = None
    """What the change event shows in a trace (default: the edits)."""


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    target: Target = "state"
    description: str
    edits: list[Edit] = Field(default_factory=list)
    response: ResponseEdit | None = None
    trigger: Trigger | None = None
    atoms: list[tuple[str, Any]] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    """Names of the hints that led to this mutation (empty for an unhinted one)."""
    touches: list[str] = Field(default_factory=list)
    """Entity fields changed, as ``collection.field`` paths, for the observability check."""
    reachable: bool = False
    """Built from the service's own operations, so the state is reachable by construction."""


@dataclass(frozen=True)
class World:
    """A state plus response edits and timers, and the mutations that produced it."""

    state: State
    response_edits: tuple[ResponseEdit, ...] = ()
    timers: tuple[Timer, ...] = ()
    path: tuple[Mutation, ...] = ()

    def apply(self, mutation: Mutation) -> World:
        state, edits, timers = self.state, self.response_edits, self.timers
        if mutation.target == "state":
            state = apply_edits(state, mutation.edits)
        elif mutation.target == "response" and mutation.response is not None:
            edits = (*edits, mutation.response)
        elif mutation.target == "timing" and mutation.trigger is not None:
            timers = (
                *timers,
                Timer(
                    name=f"{mutation.family}_{len(timers) + 1}",
                    trigger=mutation.trigger,
                    edits=mutation.edits,
                ),
            )
        return World(state, edits, timers, (*self.path, mutation))

    def fingerprint(self) -> str:
        payload = {
            "state": self.state.to_json(),
            "response": [e.model_dump(mode="json") for e in self.response_edits],
            "timers": [t.model_dump(mode="json") for t in self.timers],
        }
        return sha256_text(canonical_json(payload))[:16]

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self.state.to_json(),
            "response_edits": [e.model_dump(mode="json") for e in self.response_edits],
            "timers": [t.model_dump(mode="json") for t in self.timers],
            "path": [m.model_dump(mode="json") for m in self.path],
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> World:
        return World(
            State.from_json(data["state"]),
            tuple(ResponseEdit.model_validate(e) for e in data.get("response_edits", [])),
            tuple(Timer.model_validate(t) for t in data.get("timers", [])),
            tuple(Mutation.model_validate(m) for m in data.get("path", [])),
        )


class Mutator(Protocol):
    """Proposes mutations of a world. ``consumes`` lists the hint kinds the family reads."""

    family: str
    target: str
    consumes: frozenset[str]

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]: ...


@dataclass
class Candidate:
    """A proposed world with its validity and where it came from."""

    world: World
    group: Literal["hinted", "unhinted"] = "unhinted"
    depth: int = 1
    notes: list[str] = field(default_factory=list)


def atoms_of(mutation: Mutation) -> list[Atom]:
    return [(c, k) for c, k in mutation.atoms]
