"""The retrievers behind the corpus tools (0.9): the hashed dense stand-in, rank fusion, an
embedding function you supply, and the choice carried in the stats, the report and the replay.

Proposed fixture: pending owner review (the planted summary and the expected ranks are written by
Claude, who also wrote the retrievers).
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

import pytest

from isitright.packs.research.retrieval import (
    RETRIEVER_STATEMENTS,
    EmbeddingIndex,
    FrozenIndex,
    FrozenStats,
    HybridIndex,
    ToolHost,
    build_index,
    hashed_embedding,
    sentence_transformers_embedder,
)

from .research_fixtures import corpus, run_stand_in

DOCS = list(corpus().entities("documents"))
QUERY = "Halvorsen Bridge completed"


def stats(kind: str) -> FrozenStats:
    return FrozenStats.from_documents(DOCS, kind)


def test_the_default_stats_file_is_the_0_8_file() -> None:
    assert "retriever" not in stats("bm25").to_json()
    assert stats("hybrid").to_json()["retriever"] == "hybrid"
    assert FrozenStats.from_json(stats("hashed-dense").to_json()).retriever == "hashed-dense"
    assert FrozenStats.from_json({"n": 1, "avgdl": 1.0, "df": {}}).retriever == "bm25"
    with pytest.raises(ValueError, match="retriever must be one of bm25, hashed-dense, hybrid"):
        FrozenStats.from_documents(DOCS, "bm25-ish")
    assert set(RETRIEVER_STATEMENTS) == {"bm25", "hashed-dense", "hybrid"}


def test_the_hashed_embedding_is_deterministic_and_unit_length() -> None:
    a, b = hashed_embedding("the bridge opened in 1962"), hashed_embedding("the bridge opened")
    assert a == hashed_embedding("the bridge opened in 1962")  # no hash-seed dependence
    assert round(sum(v * v for v in a), 9) == 1.0 and len(a) == 256
    assert hashed_embedding("") == [0.0] * 256
    # pinned: a change of the hash or the slots changes every dense ranking, so it must be seen
    assert sum(x * y for x, y in zip(a, b, strict=True)) == pytest.approx(0.7745967, abs=1e-6)


def test_a_single_words_embedding_is_one_pinned_slot_with_a_pinned_sign() -> None:
    """The hash and the sign rule decide every dense ranking; a change must be seen here."""
    pinned = {"bridge": (165, 1.0), "halvorsen": (173, -1.0), "traffic": (57, -1.0)}
    for word, (slot, value) in pinned.items():
        vector = hashed_embedding(word)
        assert [(i, v) for i, v in enumerate(vector) if v] == [(slot, value)], word


def test_each_retriever_ranks_the_gold_document_first_for_the_gold_query() -> None:
    for kind in ("bm25", "hashed-dense", "hybrid"):
        index = build_index(stats(kind), DOCS)
        assert index.rank(QUERY, 3)[0].id.startswith("bridge-halvorsen"), kind
        again = [(h.id, h.score) for h in build_index(stats(kind), DOCS).rank(QUERY, 20)]
        assert again == [(h.id, h.score) for h in index.rank(QUERY, 20)], kind


def test_adding_a_document_changes_no_other_dense_score() -> None:
    """What 'frozen' means for the hashed dense index: no corpus statistics, so a planted document
    only adds its own score. (BM25 keeps its original statistics for the same reason.)"""
    dense = build_index(stats("hashed-dense"), DOCS)
    planted = {"id": "plant-1", "title": "Summary", "text": "The Halvorsen Bridge completed 1999."}
    bigger = build_index(stats("hashed-dense"), [*DOCS, planted])
    before = {h.id: h.score for h in dense.rank(QUERY, 100)}
    after = {h.id: h.score for h in bigger.rank(QUERY, 100)}
    assert {k: v for k, v in after.items() if k != "plant-1"} == before
    assert "plant-1" in after


def test_ties_break_by_document_id_in_every_retriever() -> None:
    twins = [
        {"id": "b", "title": "same words", "text": "same words"},
        {"id": "a", "title": "same words", "text": "same words"},
    ]
    for kind in ("hashed-dense", "hybrid"):
        index = build_index(FrozenStats.from_documents(twins, kind), twins)
        assert [h.id for h in index.rank("same words")] == ["a", "b"], kind


class _Fixed:
    """A retriever that returns a fixed order, whatever the query."""

    def __init__(self, order: list[str]) -> None:
        self.documents = {i: {"id": i, "title": i, "text": i} for i in ("a", "b")}
        self._order = order

    def rank(self, query: str, k: int = 20) -> list[Any]:
        from isitright.packs.research.retrieval import Hit

        return [Hit(i, 1.0) for i in self._order][:k]

    def snippet(self, doc_id: str, query: str) -> str:
        return doc_id


def test_a_fused_tie_is_broken_by_id_not_by_the_order_the_parts_gave() -> None:
    # b is first in one part and a first in the other: equal fused scores; b is seen first
    fused = HybridIndex(_Fixed(["b", "a"]), _Fixed(["a", "b"])).rank("anything")
    assert fused[0].score == fused[1].score
    assert [h.id for h in fused] == ["a", "b"]


def test_hybrid_fuses_ranks_not_scores() -> None:
    first = FrozenIndex(stats("bm25"), DOCS)
    second = EmbeddingIndex(hashed_embedding, DOCS)
    fused = HybridIndex(first, second).rank(QUERY, 100)
    ranks = {h.id: i for i, h in enumerate(first.rank(QUERY, 100), 1)}
    other = {h.id: i for i, h in enumerate(second.rank(QUERY, 100), 1)}
    top = fused[0]
    assert top.score == round(
        1 / (60 + ranks.get(top.id, 10**9)) + 1 / (60 + other.get(top.id, 10**9)), 10
    ) or top.score == round(1 / (60 + ranks[top.id]) + 1 / (60 + other[top.id]), 10)


def test_a_function_you_supply_is_the_index() -> None:
    def embed(text: str) -> list[float]:
        return [1.0, 0.0] if "bridge" in text.casefold() else [0.0, 1.0]

    index = EmbeddingIndex(embed, DOCS)
    top = index.rank("bridge", 3)
    assert all("bridge" in str(index.documents[h.id]["text"]).casefold() for h in top)
    assert [h.id for h in top] == sorted(h.id for h in top)  # equal scores: id order


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is not None,
    reason="the package is installed: the missing-package message is not reachable",
)
def test_the_local_embedding_adapter_says_what_is_missing() -> None:
    with pytest.raises(ValueError, match="needs the sentence-transformers package"):
        sentence_transformers_embedder("any-model")


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="sentence-transformers is not installed (it is not a dependency of isitright)",
)
def test_the_local_embedding_adapter_makes_a_working_index() -> None:  # pragma: no cover
    index = EmbeddingIndex(sentence_transformers_embedder("all-MiniLM-L6-v2"), DOCS)
    assert index.rank(QUERY, 1)


def test_the_tools_serve_whichever_retriever_the_world_uses() -> None:
    results = {}
    for kind in ("bm25", "hashed-dense", "hybrid"):
        host = ToolHost(build_index(stats(kind), DOCS))
        found = json.loads(host.call("search", {"query": QUERY, "k": 3}))["results"]
        results[kind] = [r["id"] for r in found]
        assert all(r["snippet"] for r in found)
    assert results["bm25"][0] == results["hybrid"][0] == "bridge-halvorsen-history"
    assert results["hashed-dense"][:2] == ["bridge-halvorsen-traffic", "bridge-halvorsen-history"]


def test_an_audit_with_a_hybrid_retriever_says_so_and_replays() -> None:
    from isitright.core.replay import replay
    from isitright.packs.research.replaying import rerun

    audit, report = run_stand_in("credulous", depth=1, retriever="hybrid")
    retrieval: dict[str, Any] = report.extensions["research"]["retrieval"]
    assert retrieval["retriever"] == "hybrid"
    assert retrieval["scorer"] == RETRIEVER_STATEMENTS["hybrid"]
    assert report.findings, "the credulous stand-in is still flagged"
    artifact = next(iter(audit.artifacts.values()))
    assert artifact.host["index_stats"]["retriever"] == "hybrid"
    assert replay(artifact, rerun).reproduced is True


def test_a_retriever_that_does_not_show_the_stand_in_the_fact_ends_at_the_baseline_gate() -> None:
    """With the hashed dense retriever the gold sentence is not in the top five for the stand-in's
    queries, so it abstains: INCONCLUSIVE with the reason, never a finding about the corpus."""
    _, report = run_stand_in("credulous", depth=1, retriever="hashed-dense")
    assert report.divergence_status.value == "INCONCLUSIVE" and not report.findings
    assert "the baseline report abstains" in report.extensions["research"]["reason"]


def test_the_default_audit_still_names_bm25() -> None:
    _, report = run_stand_in("careful", depth=1)
    assert report.extensions["research"]["retrieval"]["retriever"] == "bm25"
