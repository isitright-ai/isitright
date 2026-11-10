"""The corpus as a world: a `documents` collection, its rules and a loader.

A document is an entity: a stable ``id``, typed metadata the mutators and constraints may reason
about (``title``, ``source``, ``authority``, ``date``, ``supersedes``, ``duplicate_of``,
``retracted``) and an opaque ``text``. Only a mutator that declares a span edits the text, and it
records what it did in the document's own ``provenance`` field, so a world describes itself and a
replay needs no side table.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from isitright.core.constraints import PythonConstraint
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, RefSpec
from isitright.core.spec import ParamSpec, ToolSpec, WorldSpec
from isitright.core.world import Entity, State

COLLECTION = "documents"
RETRACTION_MARKER = "retracted"
"""A retracted document's text must say so (the rule is declared, and checked, by the pack)."""


class CorpusError(ValueError):
    """The corpus cannot be loaded: a missing file, a bad row or an unreadable document."""


def schema() -> EntitySchema:
    return EntitySchema(
        collections=[
            CollectionSpec(
                name=COLLECTION,
                key="id",
                fields=[
                    FieldSpec(name="id", type="text"),
                    FieldSpec(name="title", type="text"),
                    FieldSpec(name="source", type="text", optional=True, nullable=True),
                    FieldSpec(name="authority", type="int", optional=True, nullable=True),
                    FieldSpec(name="date", type="date", optional=True, nullable=True),
                    FieldSpec(name="text", type="text"),
                    FieldSpec(name="supersedes", type="text", optional=True, nullable=True),
                    FieldSpec(name="duplicate_of", type="text", optional=True, nullable=True),
                    FieldSpec(name="retracted", type="bool", optional=True),
                    FieldSpec(name="provenance", type="json", optional=True, nullable=True),
                ],
                references=[
                    RefSpec(field="supersedes", to=COLLECTION, enforced=False),
                    RefSpec(field="duplicate_of", to=COLLECTION, enforced=False),
                ],
            )
        ]
    )


def _iso(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _by_id(state: State) -> dict[str, Entity]:
    return {str(d["id"]): d for d in state.entities(COLLECTION)}


def _supersedes_dates(state: State) -> list[str]:
    docs = _by_id(state)
    problems = []
    for doc in docs.values():
        target = docs.get(str(doc.get("supersedes")))
        if doc.get("supersedes") is None or target is None:
            continue
        new, old = _iso(doc.get("date")), _iso(target.get("date"))
        if new is None or old is None:
            problems.append(f"{doc['id']} supersedes {target['id']} but a date is missing")
        elif new < old:
            problems.append(f"{doc['id']} ({new}) supersedes {target['id']} ({old}), an older one")
    return problems


def _no_cycles(state: State) -> list[str]:
    docs = _by_id(state)
    problems = []
    for field in ("supersedes", "duplicate_of"):
        for start in docs:
            seen, current = {start}, docs[start].get(field)
            while current is not None and current in docs:
                if current in seen:
                    problems.append(f"{field} cycle through {current}")
                    break
                seen.add(str(current))
                current = docs[str(current)].get(field)
    return sorted(set(problems))


def _not_after_cutoff(state: State) -> list[str]:
    cutoff = _iso(state.params.get("cutoff"))
    if cutoff is None:
        return []
    return [
        f"{d['id']} is dated {d['date']}, after the corpus cutoff {cutoff}"
        for d in state.entities(COLLECTION)
        if (when := _iso(d.get("date"))) is not None and when > cutoff
    ]


def _retraction_visible(state: State) -> list[str]:
    return [
        f"{d['id']} is marked retracted but its text does not say so"
        for d in state.entities(COLLECTION)
        if d.get("retracted") and RETRACTION_MARKER not in str(d["text"]).casefold()
    ]


def _authority_range(state: State) -> list[str]:
    return [
        f"{d['id']} has authority {d['authority']}, outside 0..3"
        for d in state.entities(COLLECTION)
        if d.get("authority") is not None and not 0 <= int(d["authority"]) <= 3
    ]


def rules() -> list[PythonConstraint]:
    """The metadata rules of the pack. They read dates, references and flags, never the text
    (except that a retraction notice is visible). They are check-only: no generator reads them."""
    return [
        PythonConstraint(
            "supersedes_is_newer",
            _supersedes_dates,
            "a document that supersedes another is dated no earlier than it",
        ),
        PythonConstraint(
            "no_reference_cycles", _no_cycles, "supersedes and duplicate_of chains have no cycle"
        ),
        PythonConstraint(
            "not_after_cutoff", _not_after_cutoff, "no document is dated after the corpus cutoff"
        ),
        PythonConstraint(
            "retraction_is_visible",
            _retraction_visible,
            "a retracted document's text says it was retracted",
        ),
        PythonConstraint("authority_in_range", _authority_range, "source authority is 0..3"),
    ]


def world_spec(corpus_id: str = "corpus", *, extra: Iterable[PythonConstraint] = ()) -> WorldSpec:
    return WorldSpec(
        id=corpus_id,
        schema=schema(),
        python_constraints=[*rules(), *extra],
        params=[
            ParamSpec(name="cutoff", type="date", description="No document is dated after it.")
        ],
        tools=[
            ToolSpec(
                name="search",
                description="Rank documents for a query; returns ids, titles and snippets.",
                exposes=["documents.title", "documents.text"],
            ),
            ToolSpec(
                name="open",
                description="Return one document by id.",
                exposes=[
                    "documents.title",
                    "documents.source",
                    "documents.date",
                    "documents.text",
                ],
            ),
        ],
    )


def make_state(documents: Iterable[Mapping[str, Any]], cutoff: str | None = None) -> State:
    rows: list[Entity] = []
    seen: set[str] = set()
    for raw in documents:
        row = dict(raw)
        for required in ("id", "text"):
            if required not in row or not isinstance(row[required], str):
                raise CorpusError(f"a document needs a text {required!r}: {str(raw)[:80]}")
        if row["id"] in seen:
            raise CorpusError(f"duplicate document id {row['id']!r}")
        seen.add(row["id"])
        row.setdefault("title", row["id"])
        rows.append(row)
    params = {"cutoff": cutoff} if cutoff else {}
    return State({COLLECTION: tuple(rows)}, {COLLECTION: "id"}, params)


def load_corpus(path: Path, *, cutoff: str | None = None) -> State:
    """Load ``path``: a JSONL file with one document per line, or a directory holding
    ``corpus.jsonl``, or ``*.txt``/``*.md`` files with an optional ``metadata.jsonl`` (rows with
    an ``id`` equal to the file stem, plus any metadata fields)."""
    if not path.exists():
        raise CorpusError(f"corpus {path} does not exist")
    if path.is_file():
        return make_state(_read_jsonl(path), cutoff)
    if (path / "corpus.jsonl").is_file():
        return make_state(_read_jsonl(path / "corpus.jsonl"), cutoff)
    metadata = {
        str(r["id"]): r
        for r in (
            _read_jsonl(path / "metadata.jsonl") if (path / "metadata.jsonl").is_file() else []
        )
        if "id" in r
    }
    rows = []
    for file in sorted([*path.glob("*.txt"), *path.glob("*.md")]):
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CorpusError(f"cannot read {file.name}: {error}") from error
        rows.append({**metadata.get(file.stem, {}), "id": file.stem, "text": text})
    if not rows:
        raise CorpusError(f"{path} holds no corpus.jsonl and no .txt or .md documents")
    return make_state(rows, cutoff)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError as error:
            raise CorpusError(f"{path.name} line {number} is not JSON: {error}") from error
        if not isinstance(value, dict):
            raise CorpusError(f"{path.name} line {number} is not an object")
        rows.append(value)
    return rows


def documents_of(state: State) -> dict[str, Entity]:
    return _by_id(state)
