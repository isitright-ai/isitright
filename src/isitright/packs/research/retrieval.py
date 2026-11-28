"""Frozen BM25 retrieval and the two corpus tools, `search` and `open`.

The index statistics (document frequencies, document count, average length) are computed once from
the original corpus and stay fixed when a world mutates, so a mutation changes only the ranks it
intends and a minimized corpus keeps the ranks of the documents it kept. A planted document is
scored with those frozen statistics. Ties break by document id; scores are rounded before they are
compared so the order does not depend on the platform's float summation. Nothing here uses a model.

0.9: the index is one of several retrievers behind the tools (`Retriever`): the frozen BM25, a
deterministic hashed bag-of-words embedding standing in for a dense retriever, a rank fusion of the
two, and an adapter for an embedding function you supply. ``FrozenStats.retriever`` names which one
a world uses, so the stats file and the replay artifact carry it and a replay rebuilds the same
retriever. What "frozen" means for each is in `docs/research/index.md`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

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
    retriever: str = "bm25"
    """``bm25``, ``hashed-dense`` or ``hybrid``: which retriever `build_index` makes."""

    @staticmethod
    def from_documents(
        documents: Iterable[Mapping[str, Any]], retriever: str = "bm25"
    ) -> FrozenStats:
        if retriever not in RETRIEVERS:
            raise ValueError(f"retriever must be one of {', '.join(RETRIEVERS)}, not {retriever!r}")
        df: Counter[str] = Counter()
        total = count = 0
        for doc in documents:
            tokens = tokenize(searchable(doc))
            df.update(set(tokens))
            total += len(tokens)
            count += 1
        return FrozenStats(count, total / count if count else 0.0, dict(df), retriever)

    def restricted(self, terms: Iterable[str]) -> FrozenStats:
        """Only the frequencies of ``terms``: lossless for any world whose documents and queries
        use no other term, because a term in no document never scores."""
        wanted = set(terms)
        kept = {t: c for t, c in self.df.items() if t in wanted}
        return FrozenStats(self.n, self.avgdl, kept, self.retriever)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "n": self.n,
            "avgdl": self.avgdl,
            "df": dict(sorted(self.df.items())),
        }
        if self.retriever != "bm25":  # 0.8 files stay byte-identical
            out["retriever"] = self.retriever
        return out

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> FrozenStats:
        return FrozenStats(
            int(data["n"]),
            float(data["avgdl"]),
            {str(k): int(v) for k, v in data["df"].items()},
            str(data.get("retriever", "bm25")),
        )


def terms_of(documents: Iterable[Mapping[str, Any]]) -> set[str]:
    return {t for doc in documents for t in tokenize(searchable(doc))}


@dataclass(frozen=True)
class Hit:
    id: str
    score: float


class Retriever(Protocol):
    """What the tools need from a retriever: the documents it serves, a deterministic ranking
    (equal scores in id order; scores rounded before comparing) and a snippet per result."""

    @property
    def documents(self) -> Mapping[str, Entity]: ...

    def rank(self, query: str, k: int = ...) -> list[Hit]: ...

    def snippet(self, doc_id: str, query: str) -> str: ...


def _snippet(text: str, query: str) -> str:
    """The sentence that shares the most terms with the query (the first on a tie)."""
    wanted = set(tokenize(query))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return ""
    best = max(sentences, key=lambda s: len(wanted & set(tokenize(s))))
    return best[:SNIPPET_CHARS]


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
        return _snippet(str(self.documents[doc_id].get("text") or ""), query)


RETRIEVERS = ("bm25", "hashed-dense", "hybrid")
RETRIEVER_STATEMENTS = {
    "bm25": "BM25 (k1=1.2, b=0.75), statistics frozen from the original corpus",
    "hashed-dense": (
        "a hashed bag-of-words embedding (256 slots, cosine), a deterministic stand-in for a dense "
        "retriever: no model, no corpus statistics"
    ),
    "hybrid": (
        "reciprocal rank fusion (k=60) of the frozen BM25 and the hashed bag-of-words embedding, "
        "a stand-in for a hybrid retriever"
    ),
}
DENSE_DIMENSIONS = 256
RRF_K = 60


def hashed_embedding(text: str, dimensions: int = DENSE_DIMENSIONS) -> list[float]:
    """A deterministic bag-of-words embedding: each token adds +1 or -1 to one of ``dimensions``
    slots, chosen by a hash (blake2b, so it does not depend on the interpreter's hash seed or the
    platform), then the vector is scaled to unit length. A stand-in for a dense retriever that needs
    no model and no corpus statistics: two documents' scores never depend on a third."""
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        slot = int.from_bytes(digest[:4], "big") % dimensions
        vector[slot] += 1.0 if digest[4] & 1 else -1.0
    return _unit(vector)


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else list(vector)


class EmbeddingIndex:
    """Cosine similarity over embeddings from ``embed`` (a function of one text; the vector is
    normalized here). The index is fixed by the function: a document added to a world is embedded
    by it and ranked against the others with no re-indexing.

    ``embed`` must be deterministic (the same text, the same vector); isitright cannot check that
    for a model you supply, and a non-deterministic one breaks replay."""

    def __init__(
        self, embed: Callable[[str], Sequence[float]], documents: Sequence[Entity]
    ) -> None:
        self.documents = {str(d["id"]): d for d in documents}
        self._embed = embed
        self._vectors = {
            doc_id: _unit(embed(searchable(doc))) for doc_id, doc in self.documents.items()
        }

    def rank(self, query: str, k: int = MAX_K) -> list[Hit]:
        q = _unit(self._embed(query))
        hits = []
        for doc_id, vector in self._vectors.items():
            score = sum(a * b for a, b in zip(q, vector, strict=False))
            if score > 0:
                hits.append(Hit(doc_id, round(score, 10)))
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:k]

    def snippet(self, doc_id: str, query: str) -> str:
        return _snippet(str(self.documents[doc_id].get("text") or ""), query)


class HybridIndex:
    """Reciprocal rank fusion of two retrievers: a document's score is the sum over the retrievers
    of ``1 / (RRF_K + rank)``. Ties break by id. Deterministic when its parts are."""

    def __init__(self, first: Retriever, second: Retriever) -> None:
        self.documents = first.documents
        self._parts = (first, second)

    def rank(self, query: str, k: int = MAX_K) -> list[Hit]:
        fused: dict[str, float] = {}
        for part in self._parts:
            for position, hit in enumerate(part.rank(query, len(self.documents)), start=1):
                fused[hit.id] = fused.get(hit.id, 0.0) + 1.0 / (RRF_K + position)
        hits = [Hit(doc_id, round(score, 10)) for doc_id, score in fused.items()]
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:k]

    def snippet(self, doc_id: str, query: str) -> str:
        return self._parts[0].snippet(doc_id, query)


def sentence_transformers_embedder(model: str) -> Callable[[str], list[float]]:
    """An embedding function from a local ``sentence-transformers`` model (not a dependency of
    isitright: install it yourself; the model is read from disk or your cache, and the first use may
    download it). Returns a function for `EmbeddingIndex`. Whether a given model's embeddings are
    deterministic across machines and versions is yours to check."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise ValueError("this retriever needs the sentence-transformers package") from error
    loaded = SentenceTransformer(model)
    return lambda text: [float(v) for v in loaded.encode(text, normalize_embeddings=True)]


def build_index(stats: FrozenStats, documents: Sequence[Entity]) -> Retriever:
    """The retriever a world uses, from ``stats.retriever``."""
    if stats.retriever == "bm25":
        return FrozenIndex(stats, documents)
    dense = EmbeddingIndex(hashed_embedding, documents)
    if stats.retriever == "hashed-dense":
        return dense
    if stats.retriever == "hybrid":
        return HybridIndex(FrozenIndex(stats, documents), dense)
    raise ValueError(f"unknown retriever {stats.retriever!r}")


@dataclass
class ToolHost:
    """Serves `search` and `open` over one world, applies response edits, records every call.

    It refuses every other tool name and any argument that is not of the declared type.
    ``edits`` are core `ResponseEdit`s: ``reorder`` on `search` reverses the result list,
    ``drop_field`` with field ``snippet`` empties the snippets.
    """

    index: Retriever
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
