# Proposed fixture: pending owner review (the rules encode what "valid" means for a corpus).
"""The document model, the loader and the validity rules. Each rule has a state that breaks it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from isitright.core.constraints import ValidityStatus, ValidityTier
from isitright.core.mutations import AddEntity, SetField, apply_edits
from isitright.packs.research.documents import (
    COLLECTION,
    CorpusError,
    load_corpus,
    make_state,
    world_spec,
)

from .research_fixtures import ROOT, corpus


def _spec():
    return world_spec("t")


def test_the_constructed_corpus_is_valid_to_the_domain_tier() -> None:
    validity = _spec().validate(corpus())
    assert validity.status is ValidityStatus.VALID
    assert validity.tiers == (ValidityTier.STRUCTURAL, ValidityTier.DOMAIN_VALIDATED)


def _with(state, **changes):
    key = changes.pop("key")
    return apply_edits(
        state,
        [SetField(collection=COLLECTION, key=key, path=[k], value=v) for k, v in changes.items()],
    )


def _problem(state) -> str:
    validity = _spec().validate(state)
    assert validity.status is ValidityStatus.INVALID
    return " | ".join(validity.problems)


def test_a_superseding_document_may_not_be_older() -> None:
    state = _with(corpus(), key="tolls-norrvik-2022", date="2017-01-01")
    assert "supersedes_is_newer" in _problem(state) and "an older one" in _problem(state)


def test_a_supersedes_chain_with_a_missing_date_is_invalid() -> None:
    state = _with(corpus(), key="tolls-norrvik-2022", date=None)
    assert "a date is missing" in _problem(state)


def test_reference_cycles_are_invalid() -> None:
    state = _with(corpus(), key="tolls-norrvik-2018", supersedes="tolls-norrvik-2022")
    assert "cycle through" in _problem(state)


def test_nothing_may_be_dated_after_the_cutoff() -> None:
    state = _with(
        load_corpus(ROOT / "corpus", cutoff="2024-12-31"), key="digest-2024", date="2025-02-01"
    )
    assert "after the corpus cutoff 2024-12-31" in _problem(state)


def test_a_retracted_document_must_say_so() -> None:
    state = _with(corpus(), key="bridge-eastgate", retracted=True)
    assert "marked retracted but its text does not say so" in _problem(state)


def test_authority_is_zero_to_three() -> None:
    state = _with(corpus(), key="bridge-eastgate", authority=9)
    assert "outside 0..3" in _problem(state)


def test_structural_checks_catch_a_duplicate_id_and_a_wrong_type() -> None:
    from isitright.core.mutations import EditError

    with pytest.raises(EditError, match="already has key"):
        apply_edits(
            corpus(),
            [
                AddEntity(
                    collection=COLLECTION, entity={"id": "digest-2024", "title": "x", "text": "y"}
                )
            ],
        )
    bad = _with(corpus(), key="digest-2024", text=5)
    assert "is not text" in _problem(bad)


def test_a_dangling_supersedes_reference_is_allowed_but_not_a_cycle() -> None:
    state = _with(corpus(), key="tolls-norrvik-2022", supersedes="gone")
    assert _spec().validate(state).status is ValidityStatus.VALID


def test_loader_reads_jsonl_files_and_directories(tmp_path: Path) -> None:
    rows = [{"id": "a", "text": "one", "title": "A"}, {"id": "b", "text": "two"}]
    jsonl = tmp_path / "c.jsonl"
    jsonl.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert [d["id"] for d in load_corpus(jsonl).entities(COLLECTION)] == ["a", "b"]
    assert load_corpus(jsonl).entities(COLLECTION)[1]["title"] == "b"  # a missing title is the id
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "x.txt").write_text("hello world", encoding="utf-8")
    (folder / "metadata.jsonl").write_text(
        json.dumps({"id": "x", "title": "X", "date": "2020-01-01"}), "utf-8"
    )
    loaded = load_corpus(folder, cutoff="2021-01-01")
    assert loaded.entities(COLLECTION)[0]["title"] == "X"
    assert loaded.params["cutoff"] == "2021-01-01"
    assert load_corpus(ROOT / "corpus").size() == 24


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"id": "a"}', "needs a text 'text'"),
        ('{"id": "a", "text": "x"}\n{"id": "a", "text": "y"}', "duplicate document id 'a'"),
        ("not json", "line 1 is not JSON"),
        ("[1]", "line 1 is not an object"),
    ],
)
def test_loader_errors_name_the_problem(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CorpusError, match=message):
        load_corpus(path)


def test_loader_refuses_a_missing_or_empty_corpus(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="does not exist"):
        load_corpus(tmp_path / "nope")
    with pytest.raises(CorpusError, match=r"holds no corpus\.jsonl"):
        load_corpus(tmp_path)


def test_make_state_keeps_text_opaque_and_keys_documents_by_id() -> None:
    state = make_state([{"id": "a", "text": "free text with 1962 and {braces}"}])
    assert state.atoms() == [(COLLECTION, "a")]
    assert state.entities(COLLECTION)[0]["text"] == "free text with 1962 and {braces}"
