"""World state: serializable, fingerprintable, never an engine handle.

A state holds entities in named collections plus scalar parameters (the clock, service settings).
The units of a state are its *atoms*, one per top-level entity, used for world diffs and
minimization. Embedded entities are stored as a mapping keyed by their own key and travel with
their owner.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

Entity = dict[str, Any]
Atom = tuple[str, Any]
"""(collection name, key value)."""


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for fingerprints and hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class State:
    """One concrete world. Treat the contents as read-only; derive new states with the methods.

    ``keys`` names the key field of each collection, so a state can address its own atoms.
    """

    collections: Mapping[str, tuple[Entity, ...]]
    keys: Mapping[str, str]
    params: Mapping[str, Any] = field(default_factory=dict)

    def entities(self, collection: str) -> tuple[Entity, ...]:
        return self.collections.get(collection, ())

    def get(self, atom: Atom) -> Entity | None:
        collection, key = atom
        name = self.keys[collection]
        return next((e for e in self.entities(collection) if e.get(name) == key), None)

    def atoms(self) -> list[Atom]:
        return [(c, e[self.keys[c]]) for c, rows in self.collections.items() for e in rows]

    def size(self) -> int:
        return sum(len(rows) for rows in self.collections.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "collections": {c: list(rows) for c, rows in self.collections.items()},
            "keys": dict(self.keys),
            "params": dict(self.params),
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> State:
        return State(
            {c: tuple(copy.deepcopy(rows)) for c, rows in data.get("collections", {}).items()},
            dict(data["keys"]),
            copy.deepcopy(dict(data.get("params", {}))),
        )

    def fingerprint(self) -> str:
        return sha256_text(canonical_json(self.to_json()))[:16]

    def evolve(
        self,
        collections: Mapping[str, Iterable[Entity]] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> State:
        """A copy with whole collections and/or parameters replaced."""
        merged = dict(self.collections)
        for name, rows in (collections or {}).items():
            merged[name] = tuple(rows)
        return State(merged, self.keys, {**self.params, **(params or {})})

    def mutable(self) -> dict[str, list[Entity]]:
        """A deep copy of the collections that a caller may edit and wrap again with `evolve`."""
        return {c: copy.deepcopy(list(rows)) for c, rows in self.collections.items()}

    def without(self, atoms: Iterable[Atom]) -> State:
        drop = set(atoms)
        return State(
            {
                c: tuple(e for e in rows if (c, e[self.keys[c]]) not in drop)
                for c, rows in self.collections.items()
            },
            self.keys,
            self.params,
        )


def diff_states(base: State, other: State) -> dict[str, Any]:
    """Added, removed and changed atoms of `other` relative to `base`."""
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for collection in sorted(set(base.collections) | set(other.collections)):
        name = other.keys.get(collection) or base.keys[collection]
        before = {e[name]: e for e in base.entities(collection)}
        after = {e[name]: e for e in other.entities(collection)}
        for key, entity in after.items():
            if key not in before:
                added.append({"atom": [collection, key], "entity": entity})
            elif entity != before[key]:
                changed.append(
                    {"atom": [collection, key], "fields": _field_changes(before[key], entity)}
                )
        removed.extend(
            {"atom": [collection, key], "entity": entity}
            for key, entity in before.items()
            if key not in after
        )
    params = {
        name: {"before": base.params.get(name), "after": other.params.get(name)}
        for name in sorted(set(base.params) | set(other.params))
        if base.params.get(name) != other.params.get(name)
    }
    return {"added": added, "removed": removed, "changed": changed, "params": params}


_MISSING = object()


def _field_changes(before: Entity, after: Entity, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, _MISSING), after.get(name, _MISSING)
        if old == new:
            continue
        path = f"{prefix}{name}"
        if isinstance(old, dict) and isinstance(new, dict):
            out.update(_field_changes(old, new, f"{path}."))
        else:
            out[path] = {
                "before": None if old is _MISSING else old,
                "after": None if new is _MISSING else new,
                "absent_before": old is _MISSING,
                "absent_after": new is _MISSING,
            }
    return out
