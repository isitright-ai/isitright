"""Screening without the agent, the ranking and the stopping rules (no agent process)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from isitright.core.oracles import Role
from isitright.packs.mcp.generate import (
    GeneratedWorld,
    _greedy,
    coverage_order,
    features_of,
    generate_worlds,
    select_worlds,
)
from isitright.packs.mcp.model import McpScenario, ToolCallError, load_scenario
from isitright.packs.mcp.runtime import RuntimeCaller, ServiceRuntime
from isitright.packs.mcp.screening import (
    PRIORITY,
    ScreeningClass,
    StoppingRules,
    StopState,
    eligible,
    rank,
    screen_all,
    screen_world,
    stratum_of,
)

SHOP = Path(__file__).parents[1] / "examples" / "agents" / "shop"
sys.path.insert(0, str(SHOP))


@pytest.fixture(scope="module")
def shop() -> McpScenario:
    return load_scenario(f"{SHOP / 'scenario.py'}:SCENARIO")


@pytest.fixture(scope="module")
def worlds(shop: McpScenario) -> list[GeneratedWorld]:
    found, _ = generate_worlds(shop, attempts=2500, depth=1)
    return found


def _trace(shop: McpScenario, mode: str) -> list[dict[str, Any]]:
    """What a scripted agent does in the unmutated world, recorded in-process."""
    import oracle
    import scripted_agent

    from isitright.core.mutations import World

    caller = RuntimeCaller(ServiceRuntime.for_world(shop, World(shop.base)))

    def call(tool: str, **arguments: Any) -> dict[str, Any]:
        try:
            return caller(tool, **arguments)
        except ToolCallError as error:
            raise scripted_agent.ToolError(str(error)) from error

    def reference_call(tool: str, **arguments: Any) -> dict[str, Any]:
        try:
            return call(tool, **arguments)
        except scripted_agent.ToolError as error:
            raise oracle.ToolError(str(error)) from error

    if mode == "careless":
        scripted_agent._careless(call)
    elif mode == "reference":
        oracle.reference_procedure(reference_call, scripted_agent.NAME, scripted_agent.ZIP)
    return caller.trace


def test_every_world_gets_a_class_and_none_is_dropped(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    screens = screen_all(shop, worlds, _trace(shop, "reference"))
    assert set(screens) == {w.id for w in worlds}
    classes = {s.cls for s in screens.values()}
    assert ScreeningClass.STALE in classes and ScreeningClass.RIGHT_IF_UNCHANGED in classes
    for w in worlds:
        s = screens[w.id]
        if w.role is Role.UNJUDGEABLE or not w.observable:
            assert s.cls is ScreeningClass.UNSCREENABLE
        assert s.basis


def test_a_changed_response_makes_the_recorded_behavior_stale(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    trace = _trace(shop, "reference")
    reorder = next(
        w
        for w in worlds
        if w.families == ["response_edit"] and w.world.response_edits[0].op == "reorder"
    )
    screened = screen_world(shop, reorder, trace)
    assert screened.cls is ScreeningClass.STALE and "different result" in screened.basis


def test_without_a_baseline_trace_every_world_is_unscreenable(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    screens = screen_all(shop, worlds[:20], None)
    assert {s.cls for s in screens.values()} == {ScreeningClass.UNSCREENABLE}
    assert all(s.basis == "no usable baseline trace" for s in screens.values())


def test_a_trace_that_replays_identically_is_judged_by_the_oracle(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    """With the careless agent's baseline, worlds the agent never sees differently are judged:
    right where acting is right, wrong where the oracle now says not to act."""
    trace = _trace(shop, "careless")
    screens = screen_all(shop, worlds, trace)
    kinds = {s.cls for s in screens.values()}
    assert ScreeningClass.RIGHT_IF_UNCHANGED in kinds
    for w in worlds:
        s = screens[w.id]
        if s.cls is ScreeningClass.WRONG_IF_UNCHANGED:
            assert "replay identically" in s.basis


def test_the_ranking_is_deterministic_orders_by_class_and_leaves_ineligible_out(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    screens = screen_all(shop, worlds, _trace(shop, "careless"))
    first = rank(worlds, screens, mode="screening", seed=3)
    assert [w.id for w in first] == [w.id for w in rank(worlds, screens, mode="screening", seed=3)]
    assert {w.id for w in first} == {w.id for w in eligible(worlds)}
    priorities = [PRIORITY[screens[w.id].cls] for w in first]
    assert priorities == sorted(priorities)
    random_a = [w.id for w in rank(worlds, None, mode="random", seed=1)]
    random_b = [w.id for w in rank(worlds, None, mode="random", seed=2)]
    assert random_a != random_b and sorted(random_a) == sorted(random_b)
    assert [w.id for w in rank(worlds, None, mode="coverage")] == [
        w.id for w in select_worlds(worlds, None)[0]
    ]


def _naive_greedy(keyed: list[tuple[Any, frozenset[Any]]], cap: int) -> list[Any]:
    """The 0.4 selection, scanning every world at every step (the reference for the lazy one)."""
    chosen: list[Any] = []
    taken: set[Any] = set()
    covered: set[Any] = set()
    cleared = False
    cap = min(cap, len(keyed))
    while len(chosen) < cap:
        best = None
        pick = None
        for index, (w, f) in enumerate(keyed):
            if w.id in taken:
                continue
            key = (-len(f - covered), index)
            if best is None or key < best:
                best, pick = key, (w, f)
        assert pick is not None and best is not None
        if best[0] == 0 and not cleared:
            covered.clear()
            cleared = True
            continue
        cleared = False
        chosen.append(pick[0])
        taken.add(pick[0].id)
        covered |= pick[1]
    return chosen


def test_the_lazy_greedy_order_equals_the_exhaustive_one(worlds: list[GeneratedWorld]) -> None:
    pool = eligible(worlds)
    keyed = [(w, features_of(w)) for w in pool]
    for cap in (5, 40, len(keyed)):
        lazy, _ = _greedy(keyed, cap)
        assert [w.id for w in lazy] == [w.id for w in _naive_greedy(keyed, cap)]
    assert len(coverage_order(pool)) == len(pool)


def test_a_stratum_stops_after_its_patience_and_says_so(worlds: list[GeneratedWorld]) -> None:
    pool = eligible(worlds)
    stratum = stratum_of(pool[0])
    members = [w for w in pool if stratum_of(w) == stratum]
    assert len(members) >= 4
    state = StopState(StoppingRules(stratum_patience=2, run_patience=None), pool)
    assert state.skip_reason(members[0]) is None
    state.record(members[0], found=False)
    assert state.skip_reason(members[1]) is None
    state.record(members[1], found=False)
    reason = state.skip_reason(members[2])
    assert reason is not None and f"no finding in 2 of {len(members)} worlds" in reason
    other = next(w for w in pool if stratum_of(w) != stratum)
    assert state.skip_reason(other) is None  # other strata keep running
    record = state.to_record(None)
    row = next(s for s in record.strata if (s.family, s.target, s.role) == stratum)
    assert row.stopped and row.worlds_run == 2 and row.worlds_not_run == len(members) - 2
    assert row.summary.startswith(f"no finding in 2 of {len(members)} worlds")
    assert "stratum rule" in (row.stop_reason or "")


def test_a_finding_resets_the_stratum_count(worlds: list[GeneratedWorld]) -> None:
    pool = eligible(worlds)
    stratum = stratum_of(pool[0])
    members = [w for w in pool if stratum_of(w) == stratum]
    state = StopState(StoppingRules(stratum_patience=2, run_patience=None), pool)
    state.record(members[0], found=False)
    state.record(members[1], found=True)
    state.record(members[2], found=False)
    assert state.skip_reason(members[3]) is None


def test_the_run_stops_after_consecutive_worlds_that_add_nothing(
    worlds: list[GeneratedWorld],
) -> None:
    pool = eligible(worlds)
    state = StopState(StoppingRules(stratum_patience=None, run_patience=3), pool)
    same = pool[0]
    state.record(same, found=False)  # new features
    for _ in range(3):
        assert state.run_stopped is None
        state.record(same, found=False)  # nothing new
    assert state.run_stopped and "3 consecutive worlds" in state.run_stopped
    assert state.skip_reason(pool[5]) == state.run_stopped
    state.record_budget("money")
    assert "consecutive" in (state.run_stopped or "")  # the first reason is kept
    record = state.to_record("money")
    assert record.run_stop_reason == state.run_stopped
    assert any("not run" not in s.summary and s.stopped for s in record.strata) or record.strata


def test_a_budget_stop_is_reported_with_its_kind(worlds: list[GeneratedWorld]) -> None:
    pool = eligible(worlds)
    state = StopState(StoppingRules(None, None), pool)
    state.record(pool[0], found=False)
    state.record_budget("money")
    assert state.skip_reason(pool[1]) == "money budget exhausted"
    record = state.to_record("money")
    assert record.run_stop_reason == "money budget exhausted"
    assert any(
        s.stopped and "money budget exhausted" in (s.stop_reason or "") for s in record.strata
    )


def test_the_diverse_ranking_takes_one_world_per_stratum_before_a_second(
    shop: McpScenario, worlds: list[GeneratedWorld]
) -> None:
    screens = screen_all(shop, worlds, _trace(shop, "careless"))
    order = rank(worlds, screens, mode="diverse")
    pool = eligible(worlds)
    assert {w.id for w in order} == {w.id for w in pool}
    strata = {stratum_of(w) for w in pool}
    first_round = order[: len(strata)]
    assert {stratum_of(w) for w in first_round} == strata  # every stratum before any second look
    priorities = [PRIORITY[screens[w.id].cls] for w in first_round]
    assert priorities == sorted(priorities)
    assert [w.id for w in order] == [w.id for w in rank(worlds, screens, mode="diverse", seed=9)]
