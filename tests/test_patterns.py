"""Pattern-based string generation from JSON Schema ``pattern``, in the core's value strategies."""

from __future__ import annotations

import re
import sqlite3

import pytest

from isitright import check
from isitright.core.constraints import Domain, Pattern
from isitright.core.families._util import clone_cluster
from isitright.core.hints import Hints
from isitright.core.mutations import World, apply_edits
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.values import (
    UnsupportedPattern,
    nth_pattern_value,
    pattern_value,
    unsupported_pattern,
)
from isitright.packs.sql.mapping import (
    build_model,
    generate_base_state,
    import_json_schema,
    to_state,
)
from isitright.packs.sql.sqlite_schema import introspect_schema

DDL = "CREATE TABLE ship (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, tons INTEGER)"
SCHEMA = {
    "type": "object",
    "properties": {
        "ship": {"type": "array", "items": {"properties": {"code": {"pattern": "^[A-Z]{3}$"}}}}
    },
}


def test_values_match_are_distinct_and_repeat_for_the_same_input() -> None:
    first = [nth_pattern_value("^[A-Z]{3}$", n) for n in range(1, 5)]
    assert first == ["AAA", "AAB", "AAC", "AAD"]
    assert first == [nth_pattern_value("^[A-Z]{3}$", n) for n in range(1, 5)]
    assert pattern_value(r"[a-z]{2}-\d{4}", taken=["aa-0000"]) == "ab-0000"
    assert re.fullmatch(r"^\w+@\w+\.com$", pattern_value(r"^\w+@\w+\.com$"))


def test_a_closed_domain_narrows_the_matches() -> None:
    domain = Domain(values=("cat", "dog"))
    assert pattern_value(r"^(?:cat|dog|eel)$", domain=domain) == "cat"
    assert pattern_value(r"^(?:cat|dog|eel)$", taken=["cat"], domain=domain) == "dog"
    with pytest.raises(UnsupportedPattern, match="no further value"):
        pattern_value(r"^(?:cat|dog|eel)$", taken=["cat", "dog"], domain=domain)


@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        (r"^(?=[A-Z])[A-Za-z]+$", "lookahead"),
        (r"^(?<!x)a$", "lookahead"),
        (r"^(a)\1$", "backreferences"),
        (r"^(?P<x>a)(?P=x)$", "backreferences"),
        (r"^(a)?(?(1)b|c)$", "conditional"),
        (r"^(unclosed$", "does not compile"),
    ],
)
def test_unsupported_constructs_are_reported_not_guessed(pattern: str, reason: str) -> None:
    assert reason in (unsupported_pattern(pattern) or "")
    with pytest.raises(UnsupportedPattern, match=reason):
        pattern_value(pattern)


def test_the_constraint_checks_every_regex_but_only_some_guide_generation() -> None:
    spec_rule = Pattern(path="ship.code", regex=r"^(a)\1$")
    assert spec_rule.value_domain("ship.code") == Domain(pattern=r"^(a)\1$")
    assert spec_rule.value_domain("ship.tons") is None


def _model() -> object:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(DDL)
        return build_model(introspect_schema(connection), "sqlite")


def test_json_schema_pattern_steers_the_base_state_and_copies_keep_matching() -> None:
    model = _model()
    rules = import_json_schema(model, SCHEMA)  # type: ignore[arg-type]
    assert [type(r).__name__ for r in rules] == ["Pattern"]
    base = generate_base_state(model, rules)  # type: ignore[arg-type]
    assert base is not None
    state = to_state(model, base)  # type: ignore[arg-type]
    assert state.entities("ship")[0]["code"] == "AAA"
    spec = WorldSpec(
        id="ships",
        schema=model.schema,  # type: ignore[attr-defined]
        constraints=[*model.constraints, *rules],  # type: ignore[attr-defined]
    )
    edits, _ = clone_cluster(spec, state, ("ship", 1))
    copy = edits[0].entity  # type: ignore[union-attr]
    assert copy["code"] == "AAB" and copy["id"] == 2  # letters step, and the copy still matches
    state = apply_edits(state, edits)
    assert spec.validate(state).status.value == "VALID"
    # a stepped value that leaves the pattern is replaced by the next match
    narrow = Pattern(path="ship.code", regex="^(?:AAA|ZZZ)$")
    narrow_spec = WorldSpec(
        id="ships",
        schema=model.schema,  # type: ignore[attr-defined]
        constraints=[*model.constraints, narrow],  # type: ignore[attr-defined]
    )
    edits, _ = clone_cluster(narrow_spec, to_state(model, base), ("ship", 1))  # type: ignore[arg-type]
    assert edits[0].entity["code"] == "ZZZ"  # type: ignore[union-attr]


def test_an_unsupported_pattern_is_listed_in_the_search_notes() -> None:
    model = _model()
    rules = [Pattern(path="ship.code", regex=r"^(a)\1$")]
    spec = WorldSpec(id="ships", schema=model.schema, constraints=rules)  # type: ignore[attr-defined]
    assert spec.unsupported_patterns() == [
        "ship.code: pattern '^(a)\\\\1$' uses backreferences, which value generation does not "
        "support"
    ]
    base = to_state(model, generate_base_state(model, []))  # type: ignore[arg-type]
    result = search(
        spec,
        World(base),
        Hints(),
        [],
        lambda c, v: Evaluation(Verdict.AGREE),
        budget=Budget(attempts=1),
    )
    assert any("unsupported for generation" in note for note in result.notes)


def test_a_sql_audit_with_a_pattern_schema_finds_a_divergence_on_matching_values() -> None:
    report = check(
        reference_sql="SELECT COUNT(*) FROM ship WHERE tons > 5",
        candidate_sql="SELECT COUNT(*) FROM ship WHERE tons >= 5",
        ddl=DDL,
        constraints=SCHEMA,
    )
    assert report.divergence_status.value == "COUNTEREXAMPLE_FOUND"
    rows = report.findings[0].divergence["candidate_state"]["ship"]
    assert all(re.fullmatch("[A-Z]{3}", row["code"]) for row in rows)
