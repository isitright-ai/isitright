# Proposed fixture: pending owner review (the invented corpus and the expected ranks).
"""Frozen BM25 and the two tools. Each test names the wrong implementation it would catch."""

from __future__ import annotations

import json

import pytest

from isitright.core.mutations import ResponseEdit
from isitright.packs.research.documents import COLLECTION, make_state
from isitright.packs.research.retrieval import (
    FrozenIndex,
    FrozenStats,
    ToolError,
    ToolHost,
    parse_search,
    terms_of,
)

from .research_fixtures import corpus


def _index(extra=()):
    state = corpus()
    stats = FrozenStats.from_documents(state.entities(COLLECTION))
    return stats, FrozenIndex(stats, [*state.entities(COLLECTION), *extra])


def test_the_cited_document_ranks_first_for_the_question() -> None:
    _, index = _index()
    assert (
        index.rank("When was the Halvorsen Bridge completed?", 3)[0].id
        == "bridge-halvorsen-history"
    )


def test_ties_break_by_document_id() -> None:
    state = make_state(
        [
            {"id": "b", "title": "x", "text": "alpha beta"},
            {"id": "a", "title": "x", "text": "alpha beta"},
        ]
    )
    stats = FrozenStats.from_documents(state.entities(COLLECTION))
    ranks = FrozenIndex(stats, list(state.entities(COLLECTION))).rank("alpha", 5)
    assert ranks[0].score == ranks[1].score
    assert [h.id for h in ranks] == ["a", "b"]  # a scorer that kept insertion order gives b, a


def test_statistics_are_frozen_when_a_document_is_added() -> None:
    """A re-indexed corpus would change every idf; frozen statistics leave untouched ranks alone."""
    stats, before = _index()
    plant = {"id": "zz-plant", "title": "t", "text": "Halvorsen Bridge completed 1990."}
    _, after = _index([plant])
    query = "Halvorsen Bridge completed"
    old = [h for h in before.rank(query, 50)]
    new = [h for h in after.rank(query, 50) if h.id != "zz-plant"]
    assert [(h.id, h.score) for h in old] == [(h.id, h.score) for h in new]
    reindexed = FrozenStats.from_documents([*corpus().entities(COLLECTION), plant])
    assert reindexed.df["halvorsen"] != stats.df["halvorsen"]  # what re-indexing would have moved


def test_restricted_statistics_rank_the_same() -> None:
    stats, index = _index()
    docs = list(index.documents.values())[:6]
    terms = terms_of(docs) | {"halvorsen", "bridge", "completed", "when", "was", "the"}
    small = FrozenIndex(stats.restricted(terms), docs)
    full = FrozenIndex(stats, docs)
    q = "When was the Halvorsen Bridge completed?"
    assert [(h.id, h.score) for h in small.rank(q, 9)] == [(h.id, h.score) for h in full.rank(q, 9)]


def test_stats_round_trip_through_json() -> None:
    stats, _ = _index()
    assert FrozenStats.from_json(json.loads(json.dumps(stats.to_json()))) == stats


def _host(edits=()):
    _, index = _index()
    return ToolHost(index, edits)


def test_search_and_open_return_ids_titles_snippets_and_text() -> None:
    host = _host()
    rows = parse_search(host.call("search", {"query": "Halvorsen Bridge completed", "k": 3}))
    assert rows[0]["id"] == "bridge-halvorsen-history" and set(rows[0]) == {
        "id",
        "title",
        "snippet",
    }
    assert "completed in 1962" in rows[0]["snippet"]
    shown = json.loads(host.call("open", {"id": "bridge-halvorsen-history"}))
    assert set(shown) == {"id", "title", "source", "date", "text"}  # no hidden metadata


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("fetch", {"url": "http://example.com"}, "this host serves search and open only"),
        ("search", {"query": "a", "k": 99}, "k must be an integer from 1 to 20"),
        ("search", {"query": "a", "k": True}, "k must be an integer from 1 to 20"),
        ("search", {"query": " "}, "search needs a non-empty string query"),
        ("search", {"query": "a", "page": 2}, "search takes query and k only, not page"),
        ("open", {"id": 3}, "open needs a string id"),
        ("open", {"id": "nope"}, "no document with id 'nope'"),
        ("open", {"id": "x", "path": "/etc/passwd"}, "open takes id only, not path"),
    ],
)
def test_the_tools_refuse_anything_beyond_search_and_open(tool, arguments, message) -> None:
    host = _host()
    with pytest.raises(ToolError, match=message):
        host.call(tool, arguments)
    assert host.events[-1]["is_error"] and message in host.events[-1]["result"]


def test_response_edits_reorder_and_empty_snippets() -> None:
    plain = parse_search(_host().call("search", {"query": "Halvorsen Bridge", "k": 4}))
    reversed_ = parse_search(
        _host([ResponseEdit(tool="search", op="reorder")]).call(
            "search", {"query": "Halvorsen Bridge", "k": 4}
        )
    )
    assert [r["id"] for r in reversed_] == [r["id"] for r in reversed(plain)]
    bare = parse_search(
        _host([ResponseEdit(tool="search", op="drop_field", field="snippet")]).call(
            "search", {"query": "Halvorsen Bridge", "k": 4}
        )
    )
    assert [r["id"] for r in bare] == [r["id"] for r in plain]
    assert all(r["snippet"] == "" for r in bare)
