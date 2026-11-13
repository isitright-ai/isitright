"""Frozen BM25 retrieval and the two corpus tools, `search` and `open`.

The index statistics (document frequencies, document count, average length) are computed once from
the original corpus and stay fixed when a world mutates, so a mutation changes only the ranks it
intends and a minimized corpus keeps the ranks of the documents it kept. A planted document is
scored with those frozen statistics. Ties break by document id; scores are rounded before they are
compared so the order does not depend on the platform's float summation. Nothing here uses a model.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from isitright.core.mutations import ResponseEdit
from isitright.core.world import Entity

K1 = 1.2
B = 0.75
MAX_K = 20
SNIPPET_CHARS = 240
_TOKEN = re.compile(r"\w+", re.UNICODE)
SEARCH_FIELDS = ("title", "text")


class ToolError(Exception):
    """A tool call the host refuses or cannot serve. Its text goes back to the agent."""


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def searchable(doc: Mapping[str, Any]) -> str:
    return " ".join(str(doc.get(name) or "") for name in SEARCH_FIELDS)


@dataclass(frozen=True)
class FrozenStats:
    """Corpus statistics of the original world."""

    n: int
    avgdl: float
    df: Mapping[str, int]

    @staticmethod
    def from_documents(documents: Iterable[Mapping[str, Any]]) -> FrozenStats:
        df: Counter[str] = Counter()
        total = count = 0
        for doc in documents:
            tokens = tokenize(searchable(doc))
            df.update(set(tokens))
            total += len(tokens)
            count += 1
        return FrozenStats(count, total / count if count else 0.0, dict(df))

    def restricted(self, terms: Iterable[str]) -> FrozenStats:
        """Only the frequencies of ``terms``: lossless for any world whose documents and queries
        use no other term, because a term in no document never scores."""
        wanted = set(terms)
        return FrozenStats(self.n, self.avgdl, {t: c for t, c in self.df.items() if t in wanted})

    def to_json(self) -> dict[str, Any]:
        return {"n": self.n, "avgdl": self.avgdl, "df": dict(sorted(self.df.items()))}

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> FrozenStats:
        return FrozenStats(
            int(data["n"]), float(data["avgdl"]), {str(k): int(v) for k, v in data["df"].items()}
        )


def terms_of(documents: Iterable[Mapping[str, Any]]) -> set[str]:
    return {t for doc in documents for t in tokenize(searchable(doc))}


@dataclass(frozen=True)
class Hit:
    id: str
    score: float


class FrozenIndex:
    """BM25 over a set of documents with fixed statistics."""

    def __init__(self, stats: FrozenStats, documents: Sequence[Entity]) -> None:
        self.stats = stats
        self.documents = {str(d["id"]): d for d in documents}
        self._tf: dict[str, Counter[str]] = {}
        self._len: dict[str, int] = {}
        for doc_id, doc in self.documents.items():
            tokens = tokenize(searchable(doc))
            self._tf[doc_id] = Counter(tokens)
            self._len[doc_id] = len(tokens)

    def idf(self, term: str) -> float:
        df = self.stats.df.get(term, 0)
        return math.log(1 + (self.stats.n - df + 0.5) / (df + 0.5))

    def rank(self, query: str, k: int = MAX_K) -> list[Hit]:
        terms = sorted(set(tokenize(query)))
        hits = []
        for doc_id, tf in self._tf.items():
            norm = K1 * (1 - B + B * self._len[doc_id] / (self.stats.avgdl or 1.0))
            score = 0.0
            for term in terms:
                f = tf.get(term, 0)
                if f:
                    score += self.idf(term) * f * (K1 + 1) / (f + norm)
            if score > 0:
                hits.append(Hit(doc_id, round(score, 10)))
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:k]

    def snippet(self, doc_id: str, query: str) -> str:
        """The sentence that shares the most terms with the query (the first on a tie)."""
        text = str(self.documents[doc_id].get("text") or "")
        wanted = set(tokenize(query))
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences:
            return ""
        best = max(sentences, key=lambda s: len(wanted & set(tokenize(s))))
        return best[:SNIPPET_CHARS]


@dataclass
class ToolHost:
    """Serves `search` and `open` over one world, applies response edits, records every call.

    It refuses every other tool name and any argument that is not of the declared type.
    ``edits`` are core `ResponseEdit`s: ``reorder`` on `search` reverses the result list,
    ``drop_field`` with field ``snippet`` empties the snippets.
    """

    index: FrozenIndex
    edits: Sequence[ResponseEdit] = ()
    max_k: int = MAX_K
    events: list[dict[str, Any]] = field(default_factory=list)

    TOOLS = ("search", "open")

    def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        try:
            text = self._serve(name, dict(arguments))
            error = False
        except ToolError as problem:
            text, error = str(problem), True
        self.events.append(
            {
                "index": len(self.events),
                "name": name,
                "arguments": dict(arguments),
                "result": text,
                "is_error": error,
            }
        )
        if error:
            raise ToolError(text)
        return text

    def try_call(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        try:
            return self.call(name, arguments), False
        except ToolError as problem:
            return str(problem), True

    def _serve(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "search":
            return self._search(arguments)
        if name == "open":
            return self._open(arguments)
        raise ToolError(f"unknown tool {name!r}: this host serves search and open only")

    def _search(self, arguments: dict[str, Any]) -> str:
        extra = sorted(set(arguments) - {"query", "k"})
        if extra:
            raise ToolError(f"search takes query and k only, not {', '.join(extra)}")
        query, k = arguments.get("query"), arguments.get("k", 5)
        if not isinstance(query, str) or not query.strip():
            raise ToolError("search needs a non-empty string query")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= self.max_k:
            raise ToolError(f"k must be an integer from 1 to {self.max_k}")
        results = [
            {
                "id": hit.id,
                "title": str(self.index.documents[hit.id].get("title") or ""),
                "snippet": self.index.snippet(hit.id, query),
            }
            for hit in self.index.rank(query, k)
        ]
        for edit in self.edits:
            if edit.tool != "search":
                continue
            if edit.op == "reorder":
                results.reverse()
            elif edit.op == "drop_field" and edit.field == "snippet":
                for row in results:
                    row["snippet"] = ""
        return json.dumps({"results": results}, sort_keys=True)

    def _open(self, arguments: dict[str, Any]) -> str:
        extra = sorted(set(arguments) - {"id"})
        if extra:
            raise ToolError(f"open takes id only, not {', '.join(extra)}")
        doc_id = arguments.get("id")
        if not isinstance(doc_id, str):
            raise ToolError("open needs a string id")
        doc = self.index.documents.get(doc_id)
        if doc is None:
            raise ToolError(f"no document with id {doc_id!r}")
        shown = {k: doc.get(k) for k in ("id", "title", "source", "date", "text")}
        return json.dumps(shown, sort_keys=True)


def parse_search(result: str) -> list[dict[str, Any]]:
    rows = json.loads(result)["results"]
    return [dict(r) for r in rows]
