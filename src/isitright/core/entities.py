"""The entity model: collections, typed fields, keys, references and dependent clusters.

Most agent worlds are records with keys and references. Packs map their worlds into this model
(the SQL pack from DDL, the MCP pack from a declared schema of the service state), and the
generic families, constraints and minimizer work on it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from isitright.core.world import Atom, Entity, State

FieldType = Literal["int", "float", "decimal", "text", "bool", "date", "datetime", "json"]
NUMERIC_TYPES: frozenset[str] = frozenset({"int", "float", "decimal"})
Layout = Literal["keyed"]


class ModelError(ValueError):
    """A schema, constraint or hint does not fit the entity model."""


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: FieldType = "text"
    nullable: bool = False
    optional: bool = False
    """The field may be absent from an entity (distinct from null)."""
    enum: list[Any] | None = None
    default: Any = None
    shape: dict[str, Any] | None = None
    """For a ``json`` field: the leaves it is known to hold, as a JSON Schema subset (``type``,
    ``items``, ``properties``, ``minimum``, ``maximum``). A declared shape scopes the JSON
    family."""


class RefSpec(BaseModel):
    """A reference from ``field`` to the key of another collection.

    ``to`` is a collection name, or ``collection.embedded`` for an entity embedded in another.
    ``owned`` marks a dependent cluster: the referencing entity exists only because of its target.
    ``enforced=False`` is a soft reference: a dangling value is allowed (the service does not
    check it), but the Dangling family still targets it.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    to: str
    owned: bool = False
    enforced: bool = True


class CollectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    key: str
    fields: list[FieldSpec]
    references: list[RefSpec] = Field(default_factory=list)
    embedded: list[CollectionSpec] = Field(default_factory=list)
    """Embedded entity collections, stored under the field of the same name as a mapping by key."""

    def field(self, name: str) -> FieldSpec:
        for spec in self.fields:
            if spec.name == name:
                return spec
        raise ModelError(f"collection {self.name!r} has no field {name!r}")

    def embedded_spec(self, name: str) -> CollectionSpec | None:
        return next((e for e in self.embedded if e.name == name), None)

    def reference(self, field_name: str) -> RefSpec | None:
        return next((r for r in self.references if r.field == field_name), None)


CollectionSpec.model_rebuild()


class EntitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[CollectionSpec]

    def collection(self, name: str) -> CollectionSpec:
        for spec in self.collections:
            if spec.name == name:
                return spec
        raise ModelError(f"no collection {name!r}")

    def keys(self) -> dict[str, str]:
        return {c.name: c.key for c in self.collections}

    def resolve(self, path: str) -> tuple[CollectionSpec, FieldSpec]:
        """Resolve ``collection.field`` or ``collection.embedded.field`` or raise `ModelError`."""
        parts = path.split(".")
        if len(parts) < 2:
            raise ModelError(f"path {path!r} must look like 'collection.field'")
        owner = self.collection(parts[0])
        for part in parts[1:-1]:
            nested = owner.embedded_spec(part)
            if nested is None:
                raise ModelError(f"path {path!r}: {owner.name!r} has no embedded {part!r}")
            owner = nested
        return owner, owner.field(parts[-1])

    def children_of(self, parent: str) -> list[tuple[CollectionSpec, RefSpec]]:
        """Collections with an owned reference to ``parent``: its dependent cluster."""
        return [
            (c, r) for c in self.collections for r in c.references if r.owned and r.to == parent
        ]

    def cluster(self, state: State, atom: Atom) -> set[Atom]:
        """The atom with every entity that exists only because of it, transitively."""
        found: set[Atom] = {atom}
        frontier = [atom]
        while frontier:
            collection, key = frontier.pop()
            for child, ref in self.children_of(collection):
                for entity in state.entities(child.name):
                    child_atom = (child.name, entity[child.key])
                    if entity.get(ref.field) == key and child_atom not in found:
                        found.add(child_atom)
                        frontier.append(child_atom)
        return found

    def check_structural(self, state: State) -> list[str]:
        """Keys, types, nullability, enums and enforced references."""
        problems: list[str] = []
        for spec in self.collections:
            seen: set[Any] = set()
            for entity in state.entities(spec.name):
                problems.extend(_check_entity(spec, entity, f"{spec.name}"))
                key = entity.get(spec.key)
                if key in seen:
                    problems.append(f"{spec.name}: duplicate key {key!r}")
                seen.add(key)
                for ref in spec.references:
                    value = entity.get(ref.field)
                    if ref.enforced and value is not None and not self.exists(state, ref.to, value):
                        problems.append(
                            f"{spec.name}[{key!r}].{ref.field}={value!r} references a missing "
                            f"{ref.to}"
                        )
        return problems

    def exists(self, state: State, target: str, key: Any) -> bool:
        """Whether a key exists in a collection, or in any entity's embedded collection."""
        head, _, embedded = target.partition(".")
        if not embedded:
            return state.get((head, key)) is not None
        return any(key in (e.get(embedded) or {}) for e in state.entities(head))


def _check_entity(spec: CollectionSpec, entity: Entity, where: str) -> list[str]:
    problems: list[str] = []
    label = f"{where}[{entity.get(spec.key)!r}]"
    for field_spec in spec.fields:
        if field_spec.name not in entity:
            if not field_spec.optional:
                problems.append(f"{label}.{field_spec.name} is missing")
            continue
        value = entity[field_spec.name]
        if value is None:
            if not field_spec.nullable:
                problems.append(f"{label}.{field_spec.name} is null")
            continue
        if not type_matches(field_spec.type, value):
            problems.append(f"{label}.{field_spec.name}={value!r} is not {field_spec.type}")
        elif field_spec.shape is not None:
            problems.extend(_shape_problems(field_spec, value, label))
        elif field_spec.enum is not None and value not in field_spec.enum:
            problems.append(f"{label}.{field_spec.name}={value!r} is not one of {field_spec.enum}")
    for nested in spec.embedded:
        mapping = entity.get(nested.name) or {}
        if not isinstance(mapping, dict):
            problems.append(f"{label}.{nested.name} must be a mapping by key")
            continue
        for key, inner in mapping.items():
            if inner.get(nested.key) != key:
                problems.append(f"{label}.{nested.name}[{key!r}] key does not match its entry")
            problems.extend(_check_entity(nested, inner, f"{label}.{nested.name}"))
    return problems


def _shape_problems(field_spec: FieldSpec, value: Any, label: str) -> list[str]:
    """Where a json value leaves its declared shape (a JSON Schema subset)."""
    errors = sorted(
        Draft202012Validator(field_spec.shape or {}).iter_errors(value),
        key=lambda e: [str(p) for p in e.absolute_path],
    )
    return [
        f"{label}.{field_spec.name}{''.join(f'[{p!r}]' for p in e.absolute_path)} {e.message}"
        for e in errors[:3]
    ]


def type_matches(kind: str, value: Any) -> bool:
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in {"float", "decimal"}:
        return isinstance(value, int | float | str) and not isinstance(value, bool)
    if kind in {"text", "date", "datetime"}:
        return isinstance(value, str)
    if kind == "bool":
        return isinstance(value, bool)
    return True


def parse_instant(value: Any) -> datetime:
    """An ISO-8601 timestamp or date as an aware instant (naive values are read as UTC)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
