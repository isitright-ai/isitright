"""Hints: what the task, the tool schemas, the programs and the baseline trace say matters.

Generic mutators applied blindly would mutate every field of every entity. Hints focus them.
A hint has a kind (`lookup`, `ordering`, `gate`, `scope`, `threshold` and any kind a pack or user
registers), a provenance and arguments that point into the entity model with dotted paths. Each
family declares which kinds it consumes. Hints prioritize: unhinted mutations still run on the
budget that remains.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from isitright.core.constraints import ExprEnv, Expression
from isitright.core.entities import EntitySchema, ModelError
from isitright.core.jsonpaths import shape_leaf, split_hint_path
from isitright.core.world import Entity, State


class Provenance(StrEnum):
    DECLARED = "declared"
    HARVESTED_PROGRAM = "harvested:program"
    HARVESTED_SCHEMA = "harvested:schema"
    HARVESTED_TRACE = "harvested:trace"
    PROPOSED = "proposed"
    """Reserved for 0.5 (LLM-proposed, until confirmed)."""


class Hint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str = ""
    provenance: Provenance = Provenance.DECLARED
    args: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _context: Any) -> None:
        if not self.name:
            self.name = self.kind


@dataclass(frozen=True)
class HintKind:
    """A registered kind: how to check its arguments against the entity model."""

    name: str
    check: Callable[[EntitySchema, Hint], None]


HINT_KINDS: dict[str, HintKind] = {}


def register_hint_kind(kind: HintKind) -> None:
    """Register (or replace) a hint kind. Built-ins use the same registry as user kinds."""
    HINT_KINDS[kind.name] = kind


def _need(hint: Hint, *names: str) -> None:
    missing = [n for n in names if n not in hint.args]
    if missing:
        raise ModelError(f"hint {hint.name!r} ({hint.kind}) needs {', '.join(missing)}")


def _where(schema: EntitySchema, hint: Hint) -> None:
    collection = schema.collection(hint.args["collection"])
    where = hint.args.get("where")
    if where:
        expression = Expression(str(where))
        for name in expression.names():
            collection.field(name)


def _check_lookup(schema: EntitySchema, hint: Hint) -> None:
    _need(hint, "collection", "fields", "value")
    collection = schema.collection(hint.args["collection"])
    for name in hint.args["fields"]:
        collection.field(name)
    if len(hint.args["fields"]) != len(hint.args["value"]):
        raise ModelError(f"hint {hint.name!r}: fields and value differ in length")


def _check_ordering(schema: EntitySchema, hint: Hint) -> None:
    _need(hint, "collection", "field")
    schema.collection(hint.args["collection"]).field(hint.args["field"])
    if hint.args.get("direction", "desc") not in {"asc", "desc"}:
        raise ModelError(f"hint {hint.name!r}: direction must be asc or desc")


def _check_gate(schema: EntitySchema, hint: Hint) -> None:
    _need(hint, "collection", "field", "allows")
    schema.collection(hint.args["collection"]).field(hint.args["field"])


def _check_scope(schema: EntitySchema, hint: Hint) -> None:
    _need(hint, "collection")
    _where(schema, hint)


def _check_threshold(schema: EntitySchema, hint: Hint) -> None:
    """A cut-off on a field (``path`` and ``value``) or on a collection size (``collection``
    and ``count``, optionally limited by ``where``), such as a page size.

    A cut-off on a field may say where the cut-off value itself falls: ``holds`` is the side of
    the cut-off where the condition the hint names is true (``above`` or ``below``), and
    ``inclusive`` says whether the cut-off value is on that side. They come together. Without
    them a world that sits exactly on the cut-off has no agreed right answer (is "within 24 hours"
    true at exactly 24 hours?), and a pack that judges worlds may decline to judge it.
    """
    if "count" in hint.args:
        _need(hint, "collection", "count")
        _where(schema, hint)
    else:
        _need(hint, "path", "value")
        schema.resolve(hint.args["path"])
        if ("inclusive" in hint.args) != ("holds" in hint.args):
            raise ModelError(f"hint {hint.name!r}: inclusive and holds come together")
        if "inclusive" in hint.args:
            if not isinstance(hint.args["inclusive"], bool):
                raise ModelError(f"hint {hint.name!r}: inclusive must be true or false")
            if hint.args["holds"] not in {"above", "below"}:
                raise ModelError(f"hint {hint.name!r}: holds must be above or below")


def _check_json_path(schema: EntitySchema, hint: Hint) -> None:
    """A path inside a json field (``orders.items[*].price``), optionally with other fields of
    the same entity whose value a leaf may take (``same_as``)."""
    _need(hint, "path")
    collection_name, field_name, tokens = split_hint_path(str(hint.args["path"]))
    collection = schema.collection(collection_name)
    spec = collection.field(field_name)
    if spec.type != "json":
        raise ModelError(f"{collection_name}.{field_name} is {spec.type}, not json")
    if spec.shape is not None and shape_leaf(spec.shape, tokens) is None:
        raise ModelError(f"path {hint.args['path']!r} is not in the declared shape of the field")
    for other in hint.args.get("same_as", []):
        collection.field(other)


for _kind, _check in (
    ("json_path", _check_json_path),
    ("lookup", _check_lookup),
    ("ordering", _check_ordering),
    ("gate", _check_gate),
    ("scope", _check_scope),
    ("threshold", _check_threshold),
):
    register_hint_kind(HintKind(_kind, _check))


class Hints:
    """The hints for one task: shared hints inherited from the scenario or suite, then its own."""

    def __init__(self, hints: Iterable[Hint] = ()) -> None:
        self._hints: dict[str, Hint] = {}
        for hint in hints:
            self._hints[hint.name] = hint

    def __iter__(self) -> Any:
        return iter(self._hints.values())

    def __len__(self) -> int:
        return len(self._hints)

    def of(self, *kinds: str) -> list[Hint]:
        return [h for h in self._hints.values() if h.kind in kinds]

    def get(self, name: str) -> Hint | None:
        return self._hints.get(name)

    def merged(self, task: Iterable[Hint]) -> Hints:
        """Shared hints first; a task hint with the same name overrides."""
        return Hints([*self._hints.values(), *task])

    def validate(self, schema: EntitySchema) -> None:
        """Load-time check: every hint must resolve in the entity model."""
        for hint in self._hints.values():
            kind = HINT_KINDS.get(hint.kind)
            if kind is None:
                raise ModelError(f"unknown hint kind {hint.kind!r} (hint {hint.name!r})")
            try:
                kind.check(schema, hint)
            except ModelError as error:
                raise ModelError(f"hint {hint.name!r}: {error}") from error
        for hint in self._hints.values():
            where = hint.args.get("where")
            if where:
                for ref in Expression(str(where)).hint_refs():
                    if ref not in self._hints:
                        raise ModelError(f"hint {hint.name!r} refers to unknown hint ${ref}")

    def values(self, schema: EntitySchema, state: State) -> dict[str, Any]:
        """What ``$name`` means in this state: the entities a lookup matches, else the arguments."""
        out: dict[str, Any] = {}
        for hint in self._hints.values():
            out[hint.name] = (
                lookup_matches(state, hint) if hint.kind == "lookup" else dict(hint.args)
            )
        return out

    def env(self, schema: EntitySchema, state: State, collection: str | None = None) -> ExprEnv:
        return ExprEnv(
            schema.collection(collection) if collection else None,
            state.params,
            self.values(schema, state),
        )

    def scoped(self, schema: EntitySchema, state: State, hint: Hint) -> list[Entity]:
        """Entities of a scope hint's collection that satisfy its ``where`` clause."""
        name = hint.args["collection"]
        where = hint.args.get("where")
        rows = list(state.entities(name))
        if not where:
            return rows
        expression, env = Expression(str(where)), self.env(schema, state, name)
        return [row for row in rows if expression.holds(row, env)]

    def to_json(self) -> list[dict[str, Any]]:
        return [h.model_dump(mode="json") for h in self._hints.values()]


def lookup_matches(state: State, hint: Hint) -> list[Entity]:
    """Entities matching every field of a lookup hint exactly."""
    fields, wanted = hint.args["fields"], hint.args["value"]
    return [
        e
        for e in state.entities(hint.args["collection"])
        if all(str(e.get(f)) == str(v) for f, v in zip(fields, wanted, strict=True))
    ]


def hints_from_json(data: Any) -> list[Hint]:
    """Parse the file form: a mapping ``kind: args`` or a list of ``{kind, name, args...}``."""
    if isinstance(data, Mapping):
        return [Hint(kind=str(k), args=dict(v)) for k, v in data.items()]
    out = []
    for item in data:
        item = dict(item)
        out.append(
            Hint(
                kind=item.pop("kind"),
                name=item.pop("name", ""),
                provenance=Provenance(item.pop("provenance", "declared")),
                args=item.pop("args", item),
            )
        )
    return out
