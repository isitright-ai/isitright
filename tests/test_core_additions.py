"""Core additions of 0.6: comparators, shared hint kinds, selection and live records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from isitright.core.compare import JsonComparator, NumericComparator, TextComparator
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, ModelError
from isitright.core.evidence import AuditReport, Finding, LiveRecord
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.mutations import Mutation, World
from isitright.core.oracles import Role
from isitright.core.selection import (
    Screened,
    ScreeningClass,
    StoppingRules,
    StopState,
    coverage_order,
    rank_worlds,
    stratum_of,
)
from isitright.core.world import State

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="t",
            key="id",
            fields=[FieldSpec(name="id", type="int"), FieldSpec(name="v", type="float")],
        )
    ]
)


def test_numeric_comparator_uses_a_stated_tolerance_and_basis() -> None:
    cmp = NumericComparator(0.01, 0.0, "the question asks for 2 decimal places")
    assert cmp.compare(1.234, 1.24).matches
    miss = cmp.compare(1.0, 1.5)
    assert not miss.matches and "2 decimal places" in (miss.difference or "")
    relative = NumericComparator(0.0, 0.1, "ten percent")
    assert relative.compare(100, 109).matches and not relative.compare(100, 111).matches
    assert cmp.describe() == {
        "kind": "numeric",
        "abs_tol": 0.01,
        "rel_tol": 0.0,
        "basis": "the question asks for 2 decimal places",
    }


def test_numeric_comparator_handles_non_finite_values_and_non_numbers() -> None:
    cmp = NumericComparator(1e-9, 1e-9, "noise")
    assert cmp.compare(float("nan"), float("nan")).matches
    assert not cmp.compare(float("inf"), 1.0).matches
    assert cmp.compare("abc", 1.0).inconclusive
    with pytest.raises(ValueError, match="basis"):
        NumericComparator(0.1, 0.0, "")
    with pytest.raises(ValueError, match="non-negative"):
        NumericComparator(-1.0, 0.0, "x")


def test_text_comparator_exact_or_normalized() -> None:
    assert TextComparator().compare(" Yes ", "yes").matches
    assert not TextComparator("none").compare("Yes", "yes").matches
    assert TextComparator("none").describe() == {"kind": "text", "normalize": "none"}
    with pytest.raises(ValueError, match="normalize"):
        TextComparator("loose")


def test_json_comparator_describes_itself() -> None:
    assert JsonComparator(frozenset({"b", "a"})).describe() == {
        "kind": "json",
        "ignore_keys": ["a", "b"],
    }


def test_column_literal_and_tolerance_hints_resolve_against_the_schema() -> None:
    hints = Hints(
        [
            Hint(kind="column", args={"collection": "t", "field": "v"}),
            Hint(kind="literal", args={"path": "t.v", "value": 3}),
            Hint(
                kind="tolerance",
                args={"abs": 0.01, "basis": "two decimal places", "path": "t.v"},
                provenance=Provenance.HARVESTED_QUESTION,
            ),
        ]
    )
    hints.validate(SCHEMA)
    assert hints.of("tolerance")[0].provenance.value == "harvested:question"
    with pytest.raises(ModelError):
        Hints([Hint(kind="column", args={"collection": "t", "field": "nope"})]).validate(SCHEMA)
    with pytest.raises(ModelError, match="abs or rel"):
        Hints([Hint(kind="tolerance", args={"basis": "x"})]).validate(SCHEMA)
    with pytest.raises(ModelError, match="basis"):
        Hints([Hint(kind="tolerance", args={"abs": 1})]).validate(SCHEMA)


@dataclass
class FakeWorld:
    id: str
    world: World
    role: Role = Role.CONTROL
    observable: bool = True


def _world(identifier: str, family: str, touches: str = "t.v") -> FakeWorld:
    mutation = Mutation(family=family, description=identifier, touches=[touches])
    return FakeWorld(identifier, World(State({}, {}), path=(mutation,)))


def test_ranking_puts_wrong_if_unchanged_first_and_is_deterministic() -> None:
    worlds = [_world("a", "boundary"), _world("b", "missing"), _world("c", "duplicate")]
    screens = {
        "a": Screened(ScreeningClass.RIGHT_IF_UNCHANGED, ""),
        "b": Screened(ScreeningClass.WRONG_IF_UNCHANGED, ""),
        "c": Screened(ScreeningClass.UNSCREENABLE, ""),
    }
    strict = [w.id for w in rank_worlds(worlds, screens, mode="screening")]
    assert strict[0] == "b" and strict[-1] == "a"
    assert next(iter(rank_worlds(worlds, screens, mode="diverse"))).id == "b"
    assert [w.id for w in rank_worlds(worlds, None, mode="coverage")] == [
        w.id for w in coverage_order(worlds)
    ]
    assert [w.id for w in rank_worlds(worlds, screens, mode="random", seed=3)] == [
        w.id for w in rank_worlds(worlds, screens, mode="random", seed=3)
    ]
    hidden = FakeWorld("h", worlds[0].world, observable=False)
    assert "h" not in {w.id for w in rank_worlds([*worlds, hidden], screens, mode="screening")}


def test_a_stratum_stops_after_its_patience_and_says_how_many_worlds_it_skipped() -> None:
    pool = [_world(f"w{i}", "boundary") for i in range(5)] + [_world("x", "missing")]
    state = StopState(StoppingRules(stratum_patience=2, run_patience=None), pool)
    state.record(pool[0], found=False)
    state.record(pool[1], found=False)
    reason = state.skip_reason(pool[2])
    assert reason is not None and "no finding in 2 of 5 worlds" in reason
    assert state.skip_reason(pool[5]) is None
    record = state.to_record(None)
    assert [s.stopped for s in record.strata if s.family == "boundary"] == [True]
    assert stratum_of(pool[0]) == ("boundary", "state", "control")


def test_a_live_record_is_part_of_a_finding_and_old_reports_still_load(tmp_path: Path) -> None:
    schema_fields = Finding.model_fields
    assert "mode" in schema_fields and "live" in schema_fields
    record = LiveRecord(
        status="CONFIRMED",
        runs=3,
        baseline_runs=3,
        not_met=2,
        program_changed_runs=1,
        found_by_frozen_replay=True,
    )
    assert record.agent_runs_only
    snapshot = Path(__file__).parent / "snapshots" / "case_report.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["schema_version"] = "0.5"
    for case in data["cases"]:
        for finding in case["findings"]:
            finding.pop("mode", None)
            finding.pop("live", None)
    report = AuditReport.model_validate(data)
    assert report.schema_version == "0.5"
    assert all(f.mode is None and f.live is None for c in report.cases for f in c.findings)
