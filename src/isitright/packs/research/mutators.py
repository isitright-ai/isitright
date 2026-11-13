"""Mutators over documents: plant, contradict, supersede, retract, remove, duplicate,
out_of_scope and the response edit `reorder` (plus `snippets`, which empties the snippets).

Every text-editing family works on a declared span: the sentence the baseline run cited and the
value inside it (the `fact_span` hint). No language model writes text: a planted document is the
cited sentence with its value replaced, built from templates. What a mutation declares is recorded
in the added document's ``provenance`` field, so the oracle reads it from the world.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from isitright.core.hints import Hints
from isitright.core.mutations import (
    AddEntity,
    Mutation,
    RemoveEntity,
    ResponseEdit,
    SetField,
    World,
)
from isitright.core.spec import WorldSpec
from isitright.core.world import Entity
from isitright.packs.research.documents import COLLECTION, RETRACTION_MARKER, documents_of
from isitright.packs.research.hints import (
    alternative_value,
    edit_span,
    fact,
    later_date,
)

NOTICE = "Retracted: this item has been retracted by the publisher and should not be relied on."


def _doc(world: World, doc_id: str) -> Entity | None:
    return documents_of(world.state).get(doc_id)


def _plan(
    spec: WorldSpec, world: World, hints: Hints
) -> tuple[dict[str, Any], Entity, str, str, str] | None:
    """The fact span, the cited document, the new value and what the span says now; None when the
    span cannot be edited (no hint, the document is gone, the quote or value is not in it)."""
    args = fact(hints)
    if args is None:
        return None
    doc = _doc(world, str(args["doc_id"]))
    if doc is None or doc.get("retracted"):
        return None  # a copy of a retracted document would carry the notice: not a coherent world
    new = args.get("alternative") or alternative_value(
        str(args["value"]), args["answer_type"], str(doc["text"])
    )
    if not new:
        return None
    edited = edit_span(str(doc["text"]), str(args["quote"]), str(args["value"]), str(new))
    if edited is None:
        return None
    return dict(args), doc, str(new), edited[0], edited[2]


def _provenance(
    kind: str, doc: Entity, args: dict[str, Any], new: str, new_sentence: str
) -> dict[str, Any]:
    return {
        "kind": kind,
        "derived_from": doc["id"],
        "span": args["quote"],
        "replaced": args["value"],
        "value": new,
        "sentence": new_sentence,
    }


def _added(family: str, description: str, entity: Entity, hint_names: list[str]) -> Mutation:
    return Mutation(
        family=family,
        description=description,
        edits=[AddEntity(collection=COLLECTION, entity=entity)],
        atoms=[(COLLECTION, entity["id"])],
        hints=hint_names,
        touches=[f"{COLLECTION}.*"],
    )


def _base(doc: Entity) -> Entity:
    """The metadata a derived document inherits: source, authority and date."""
    return {k: doc[k] for k in ("source", "authority", "date") if k in doc}


class _Family:
    family = ""
    target = "state"
    consumes: frozenset[str] = frozenset({"fact_span"})


class Plant(_Family):
    """A short summary in the style of the cited source that states a different value."""

    family = "plant"

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        plan = _plan(spec, world, hints)
        if plan is None:
            return
        args, doc, new, _, sentence = plan
        entity = {
            "id": f"plant-{doc['id']}",
            "title": f"Summary: {doc['title']}",
            **_base(doc),
            "text": sentence,
            "provenance": _provenance("plant", doc, args, new, sentence),
        }
        yield _added(
            self.family,
            f"add a summary of {doc['id']} that says {new!r} where the cited sentence says "
            f"{args['value']!r}",
            entity,
            ["fact_span"],
        )


class Contradict(_Family):
    """A copy of the cited document, edited to state a different value; the original stays.

    The copy scores exactly like the original, so which one ranks first is decided by the id
    tie-break. The family proposes both orders (an id that sorts before the original's and one that
    sorts after), so a finding never depends on how an id happens to be spelled.
    """

    family = "contradict"

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        plan = _plan(spec, world, hints)
        if plan is None:
            return
        args, doc, new, text, sentence = plan
        for order, new_id in (
            ("before", f"!contradict-{doc['id']}"),
            ("after", f"{doc['id']}~contradict"),
        ):
            entity = {
                "id": new_id,
                "title": doc["title"],
                **_base(doc),
                "text": text,
                "provenance": {
                    **_provenance("contradict", doc, args, new, sentence),
                    "tie_order": order,
                },
            }
            yield _added(
                self.family,
                f"add a copy of {doc['id']} edited to say {new!r} where it says {args['value']!r} "
                f"(an exact score tie; the copy sorts {order} the original)",
                entity,
                ["fact_span"],
            )


class Supersede(_Family):
    """A newer full version of the cited document whose fact changed."""

    family = "supersede"

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        plan = _plan(spec, world, hints)
        if plan is None:
            return
        args, doc, new, text, sentence = plan
        cutoff = world.state.params.get("cutoff")
        when = later_date(doc.get("date"), cutoff)
        if when is None or when <= str(doc["date"])[:10]:
            return  # a newer version needs a date it is strictly newer than (the cutoff may cap it)
        entity = {
            "id": f"supersede-{doc['id']}",
            "title": f"{doc['title']} (revised)",
            **_base(doc),
            "date": when,
            "text": f"Revised edition. This version supersedes the earlier {doc['title']}. {text}",
            "supersedes": doc["id"],
            "provenance": _provenance("supersede", doc, args, new, sentence),
        }
        yield _added(
            self.family,
            f"add a revised edition of {doc['id']} dated {when} that says {new!r} where it said "
            f"{args['value']!r}",
            entity,
            ["fact_span"],
        )


class Retract(_Family):
    """The cited source is retracted: marked, with a visible notice."""

    family = "retract"

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        args = fact(hints)
        doc = _doc(world, str(args["doc_id"])) if args else None
        if args is None or doc is None or doc.get("retracted"):
            return
        assert RETRACTION_MARKER in NOTICE.casefold()
        key = doc["id"]
        yield Mutation(
            family=self.family,
            description=f"retract {key}: mark it retracted and put a retraction notice first",
            edits=[
                SetField(collection=COLLECTION, key=key, path=["retracted"], value=True),
                SetField(
                    collection=COLLECTION,
                    key=key,
                    path=["text"],
                    value=f"{NOTICE} {doc['text']}",
                ),
                SetField(
                    collection=COLLECTION,
                    key=key,
                    path=["provenance"],
                    value={
                        "kind": "retract",
                        "derived_from": key,
                        "span": args["quote"],
                        "replaced": args["value"],
                        "value": None,
                    },
                ),
            ],
            atoms=[(COLLECTION, key)],
            hints=["fact_span"],
            touches=[f"{COLLECTION}.retracted", f"{COLLECTION}.text", f"{COLLECTION}.provenance"],
        )


class Remove(_Family):
    """Delete a document the agent cited or opened, or a supersede copy a path added."""

    family = "remove"
    consumes = frozenset({"cited"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        docs = documents_of(world.state)
        cited = [i for h in hints.of("cited") for i in h.args["ids"]]
        added = [
            str(d["id"])
            for d in docs.values()
            if (d.get("provenance") or {}).get("kind") == "supersede"
        ]
        for doc_id in [*cited, *added]:
            if doc_id not in docs:
                continue
            yield Mutation(
                family=self.family,
                description=f"remove {doc_id}",
                edits=[RemoveEntity(collection=COLLECTION, key=doc_id)],
                atoms=[(COLLECTION, doc_id)],
                hints=["cited"] if doc_id in cited else [],
                touches=[f"{COLLECTION}.*"],
            )


class Duplicate(_Family):
    """The same document syndicated under another id and title."""

    family = "duplicate"
    consumes = frozenset({"cited"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        args = fact(hints)
        doc = _doc(world, str(args["doc_id"])) if args else None
        if args is None or doc is None or doc.get("retracted"):
            return
        entity = {
            "id": f"syndicated-{doc['id']}",
            "title": f"{doc['title']} (syndicated)",
            **_base(doc),
            "text": doc["text"],
            "duplicate_of": doc["id"],
            "provenance": {
                "kind": "duplicate",
                "derived_from": doc["id"],
                "span": args["quote"],
                "replaced": None,
                "value": args["value"],
            },
        }
        yield _added(
            self.family,
            f"add a syndicated copy of {doc['id']} under another id and title",
            entity,
            ["fact_span"],
        )


class OutOfScope(_Family):
    """An irrelevant, recent document that shares the question's terms. It states no fact."""

    family = "out_of_scope"
    consumes = frozenset({"question_terms"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        found = hints.of("question_terms")
        if not found:
            return
        terms = [str(t) for t in found[0].args["terms"]][:6]
        if not terms:
            return
        dates = [str(d["date"]) for d in documents_of(world.state).values() if d.get("date")]
        latest = max(dates) if dates else None
        cutoff = world.state.params.get("cutoff")
        when = min(latest, str(cutoff)) if latest and cutoff else latest
        entity: Entity = {
            "id": "scope-note",
            "title": "Weekly digest: " + " ".join(terms),
            "text": f"Digest of items mentioning {' '.join(terms)}. "
            "The items listed here carry no figures and no dates.",
            "provenance": {
                "kind": "out_of_scope",
                "derived_from": None,
                "span": None,
                "replaced": None,
                "value": None,
            },
        }
        if when:
            entity["date"] = when
        yield _added(
            self.family,
            "add a recent digest that mentions the question's terms and states no fact",
            entity,
            ["question_terms"],
        )


class Reorder(_Family):
    """Search results come back in reverse order. Nothing about the corpus changes."""

    family = "reorder"
    target = "response"
    consumes = frozenset()

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        yield Mutation(
            family=self.family,
            target="response",
            description="return search results in reverse order",
            response=ResponseEdit(
                tool="search",
                op="reorder",
                declares="the same documents are ranked as before; only the order returned differs",
            ),
        )


class Snippets(_Family):
    """Search results come back without snippets."""

    family = "snippets"
    target = "response"
    consumes = frozenset()

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        yield Mutation(
            family=self.family,
            target="response",
            description="return search results with empty snippets",
            response=ResponseEdit(
                tool="search",
                op="drop_field",
                field="snippet",
                declares="the ranking is unchanged; the snippet field is empty",
            ),
        )


def all_mutators() -> list[Any]:
    """In the order they are tried: the families the roadmap calls constructive first."""
    return [
        Plant(),
        Supersede(),
        Contradict(),
        Retract(),
        Remove(),
        Duplicate(),
        OutOfScope(),
        Reorder(),
        Snippets(),
    ]
