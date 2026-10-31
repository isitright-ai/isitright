"""Acceptance of the shop support-desk scenario by execution: real agent processes, real servers.

The service and the hand-written worlds are Claude's, the judge (invariants, expectations,
reference procedure) is an OpenAI model's, and the scripted agents here are Claude's. These tests
check that they agree, now through the declared scenario: the hand-written worlds run as fixed
worlds, and the core's roles must match the oracle author's own expectations. A failure is evidence
about the service, the judge or the policy, never a reason to edit the judge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from isitright.core.evidence import AuditReport, DivergenceStatus
from isitright.core.oracles import Role
from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.model import McpScenario, load_scenario
from isitright.packs.mcp.oracle import reference_outcome
from isitright.packs.mcp.replay import replay_report
from isitright.packs.mcp.runtime import ServiceRuntime
from isitright.packs.mcp.serve import world_of

SHOP = Path(__file__).parents[1] / "examples" / "agents" / "shop"
AGENT = f'"{sys.executable}" "{SHOP / "scripted_agent.py"}"'
REF = f"{SHOP / 'scenario.py'}:SCENARIO"
ACTING = {"W0", "W2", "W3", "W10", "B03", "B05", "B08", "B09", "B18", "B20", "B21", "B22"}
# where the right behavior is to change things (W: oracle author; B: blind-world proposer)


def _cls(world_id: str) -> str:
    return world_id.split("_", 1)[0]


@pytest.fixture(scope="module")
def scenario() -> McpScenario:
    return load_scenario(REF)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[AuditReport, Path]]:
    results = {}
    for mode in ("reference", "careless", "refuse"):
        output = tmp_path_factory.mktemp(mode) / "out"
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("SHOP_AGENT_MODE", mode)
            report = run_scenario(
                scenario_ref=REF,
                agent_command=AGENT,
                output_dir=output,
                worlds="fixed",
                k=1,
                sequential=False,  # one run per hand-written world, as the assertions below count
                trust_code=True,
                timeout_seconds=120,
            )
        results[mode] = (report, output)
    return results


def _fixed_runs(report: AuditReport) -> dict[str, dict[str, Any]]:
    return {
        _cls(r["world_id"]): r
        for r in report.cases[0].extensions["mcp"]["runs"]
        if r["fixed_id"] is not None
    }


def _violated(report: AuditReport) -> dict[str, set[str]]:
    return {c: {v["invariant"] for v in r["violations"]} for c, r in _fixed_runs(report).items()}


def _met(report: AuditReport) -> dict[str, bool | None]:
    return {c: r["expectation_met"] for c, r in _fixed_runs(report).items()}


# --- the scenario itself ------------------------------------------------------------------------


def test_every_world_is_valid_and_complete(runs: dict[str, tuple[AuditReport, Path]]) -> None:
    case = runs["refuse"][0].cases[0]
    fixed = [w for w in case.worlds if w.id != "baseline"]
    assert [_cls(w.id) for w in fixed] == [
        *(f"W{n}" for n in range(12)),
        *(f"B{n:02d}" for n in (3, 5, 6, 8, 9, 10, 11, 15, 18, 20, 21, 22)),
    ]
    assert all(w.validity.status == "VALID" and w.validity.problems == [] for w in fixed)
    assert "DOMAIN_VALIDATED" in case.validity.tiers
    assert case.execution_fidelity.found_on == "SIMULATED"
    assert case.attribution_status.value == "UNDETERMINED"


def test_find_customer_shows_payment_methods(service) -> None:  # type: ignore[no-untyped-def]
    found = service.find_customer(service.baseline(), {"name": "Maria Lopez", "zip": "10027"})
    assert set(found["customers"][0]["payment_methods"]) == {"pm_visa", "pm_mc"}


def test_computed_roles_match_the_oracle_authors_labels(scenario: McpScenario) -> None:
    """The reference procedure's roles must agree with what the oracle's own expectations demand."""
    computed = {
        _cls(w.id): reference_outcome(scenario, *world_of(scenario, w)).role
        for w in scenario.fixed_worlds
    }
    assert {c for c, role in computed.items() if role is Role.CONTROL} == ACTING
    labelled = {_cls(w.id) for w in scenario.fixed_worlds if w.role == "control"}
    assert labelled == ACTING - {"W0"}  # W0 is the baseline; acting is also right there


# --- the oracle's reference procedure: service and judge agree ----------------------------------


def test_the_reference_agent_meets_every_expectation_and_breaks_no_invariant(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    report, _ = runs["reference"]
    case = report.cases[0]
    assert case.findings == []
    assert all(met is True for met in _met(report).values())
    assert case.controls is not None and case.controls.status == "DISCRIMINATING"
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    wrote = {c for c, r in _fixed_runs(report).items() if r["write_calls"]}
    assert wrote == ACTING


def test_the_core_oracle_and_the_authors_expectations_agree_for_every_agent(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    for mode, (report, _) in runs.items():
        for cls, run in _fixed_runs(report).items():
            assert (run["outcome"] == "MET") == run["expectation_met"], (mode, cls)


# --- a careless agent ---------------------------------------------------------------------------


def test_a_careless_agent_triggers_invariants_in_the_trap_worlds(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    report, _ = runs["careless"]
    violated = _violated(report)
    assert violated["W0"] == set() and violated["W7"] == set()
    assert violated["W1"] == {"unique_identity"}
    assert violated["W6"] == {"paired_changes"}
    assert violated["W10"] == {"safe_refund", "paired_changes"}
    assert "cancel_only_pending" in violated["W8"] and "safe_refund" in violated["W8"]
    for class_id in ("W2", "W3", "W4", "W5", "W11"):
        assert violated[class_id] == {"cancel_only_pending"}, class_id
    # Taking the later of two tied orders breaks no stated invariant: the expectation catches it.
    assert violated["W9"] == set() and _met(report)["W9"] is False
    # Blind worlds: a retry after an empty reply double-writes; hidden payments leave a half job.
    assert violated["B03"] == violated["B06"] == {"cancel_only_pending"}
    assert violated["B08"] == {"safe_refund", "paired_changes"}
    assert violated["B09"] == {"cancel_only_pending"}
    assert violated["B10"] == {"cancel_only_pending", "safe_refund"}
    assert violated["B11"] == {"paired_changes"}
    # Acting on the wrong order (o3 by text, not o2 by instant) breaks no stated invariant.
    assert violated["B05"] == set() and _met(report)["B05"] is False


def test_a_careless_agent_fails_the_expectation_everywhere_except_where_luck_helps(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    report, _ = runs["careless"]
    assert {c for c, met in _met(report).items() if met} == {
        "W0",
        "W7",
        "B15",
        "B18",
        "B20",
        "B21",
        "B22",
    }


def test_the_mid_run_change_is_traced_after_the_triggering_call_and_is_not_a_call(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    report, output = runs["careless"]
    run = _fixed_runs(report)["W11"]
    rows = [
        json.loads(line)
        for line in (output / run["run_dir"] / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    names = [row["name"] for row in rows]
    assert names == [
        "find_customer",
        "list_orders",
        "get_order",
        "__world_change__",
        "cancel_order",
        "refund",
    ]
    change = rows[3]
    assert change["arguments"] == {"order_id": "o3", "status": "shipped"}
    assert (change["result"], change["is_error"]) == ("", False)
    assert (run["tool_calls"], run["write_calls"]) == (5, 2)


# --- an agent that does nothing -----------------------------------------------------------------


def test_an_agent_that_refuses_everything_is_caught_by_the_controls(
    runs: dict[str, tuple[AuditReport, Path]],
) -> None:
    report, _ = runs["refuse"]
    case = report.cases[0]
    assert not any(_violated(report).values())
    assert {c for c, met in _met(report).items() if met is False} == ACTING
    assert case.controls is not None and case.controls.status == "NOT_DISCRIMINATING"
    assert all(r["tool_calls"] == 0 for r in case.extensions["mcp"]["runs"])


# --- replay -------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["reference", "careless", "refuse"])
def test_replay_reproduces_every_run(
    runs: dict[str, tuple[AuditReport, Path]], mode: str, scenario: McpScenario
) -> None:
    report, output = runs[mode]
    outcomes = replay_report(report, scenario, output)
    assert len(outcomes) == 25  # 24 hand-written worlds and the baseline
    assert all(o.reproduced for o in outcomes), [o for o in outcomes if not o.reproduced]


# --- the service and worlds, without agents -----------------------------------------------------


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend(str(SHOP))
    import shop_service

    return shop_service


def test_validity_rules_reject_broken_states(service) -> None:  # type: ignore[no-untyped-def]
    broken = service.baseline()
    broken["orders"]["o3"]["customer_id"] = "nobody"
    broken["payments"]["p3"]["amount"] = 59
    broken["orders"]["o2"]["created_at"] = "2025-01-01T00:00:00Z"
    broken["refunds"].append(
        {"id": "r1", "payment_id": "p404", "order_id": "o3", "method_id": "pm_mc", "amount": 1}
    )
    problems = " | ".join(service.validate(broken))
    for fragment in ("unknown customer", "payments sum", "created after now", "unknown payment"):
        assert fragment in problems
    assert service.validate(service.baseline()) == []


def test_the_declared_constraints_reject_what_the_services_rules_reject(
    scenario: McpScenario,
) -> None:
    from isitright.core.constraints import ValidityStatus
    from isitright.core.mutations import SetField, apply_edits

    assert scenario.spec.validate(scenario.base).status is ValidityStatus.VALID
    for edit in (
        SetField(collection="orders", key="o3", path=["customer_id"], value="nobody"),
        SetField(collection="payments", key="p3", path=["amount"], value=59),
        SetField(collection="orders", key="o2", path=["created_at"], value="2025-01-01T00:00:00Z"),
    ):
        state = apply_edits(scenario.base, [edit])
        assert scenario.spec.validate(state).status is ValidityStatus.INVALID


def test_listing_order_and_page_size_come_from_the_state(service) -> None:  # type: ignore[no-untyped-def]
    w2 = service.WORLD_BUILDERS["W2"]()
    first = service.list_orders(w2, {"customer_id": "c1"})
    second = service.list_orders(w2, {"customer_id": "c1", "page": 2})
    assert (len(first["orders"]), first["has_more"], first["total_orders"]) == (10, True, 11)
    assert [o["id"] for o in second["orders"]] == ["o3"] and not second["has_more"]
    assert first["orders"][-1]["id"] == "o2"
    w3 = service.WORLD_BUILDERS["W3"]()
    assert [o["id"] for o in service.list_orders(w3, {"customer_id": "c1"})["orders"]] == [
        "o2",
        "o3",
        "o1",
    ]
    w3["service"]["page_size"] = 2
    assert service.list_orders(w3, {"customer_id": "c1"})["has_more"] is True


def test_the_service_checks_formats_and_ids_and_nothing_else(service) -> None:  # type: ignore[no-untyped-def]
    state = service.baseline()
    with pytest.raises(ValueError, match="not found"):
        service.get_order(state, {"order_id": "o404"})
    with pytest.raises(ValueError, match="reason"):
        service.cancel_order(state, {"order_id": "o3", "reason": "whim"})
    with pytest.raises(ValueError, match="amount"):
        service.refund(state, {"payment_id": "p3", "amount": -5})
    with pytest.raises(ValueError, match="page_size"):
        service.list_orders(state, {"customer_id": "c1", "page_size": 0})
    # No policy enforced: another customer's shipped order cancels, and refunds are not capped.
    service.cancel_order(state, {"order_id": "o9", "reason": "no longer needed"})
    service.cancel_order(state, {"order_id": "o2", "reason": "no longer needed"})
    first = service.refund(state, {"payment_id": "p1", "amount": 400})
    again = service.refund(state, {"payment_id": "p1", "amount": 400, "method_id": "pm_mc"})
    assert [first["id"], again["id"], again["method_id"]] == ["r1", "r2", "pm_mc"]
    assert state["orders"]["o9"]["status"] == "cancelled"


def test_a_missing_original_method_is_a_refund_error_unless_another_is_named(service) -> None:  # type: ignore[no-untyped-def]
    state = service.WORLD_BUILDERS["W6"]()
    with pytest.raises(ValueError, match="original payment method is not available"):
        service.refund(state, {"payment_id": "p3", "amount": 60})
    with pytest.raises(ValueError, match="not found"):
        service.refund(state, {"payment_id": "p3", "amount": 60, "method_id": "pm_other"})
    assert service.refund(state, {"payment_id": "p3", "amount": 60, "method_id": "pm_visa"})


def test_the_w11_interference_ships_the_newest_order_after_its_first_read(
    scenario: McpScenario,
) -> None:
    world, interferences = world_of(scenario, scenario.fixed("W11_status_changes_mid_run"))
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    assert runtime.after_call("get_order", {"order_id": "o2"}) == []
    assert runtime.after_call("list_orders", {"customer_id": "c1"}) == []
    changes = runtime.after_call("get_order", {"order_id": "o3"})
    assert changes == [{"order_id": "o3", "status": "shipped"}]
    assert runtime.service["orders"]["o3"]["status"] == "shipped"
    assert runtime.after_call("get_order", {"order_id": "o3"}) == []


def test_blind_world_service_behaviors(service) -> None:  # type: ignore[no-untyped-def]
    builders = service.WORLD_BUILDERS
    capped = builders["B03"]()
    page = service.list_orders(capped, {"customer_id": "c1", "page_size": 50})
    assert (page["page_size"], len(page["orders"]), page["has_more"]) == (2, 2, True)
    assert service.get_order(builders["B11"](), {"order_id": "o3"})["payments"] == []
    state = builders["B08"]()
    assert service.refund(state, {"payment_id": "p3", "amount": 60}) == {}
    assert service.refund(state, {"payment_id": "p3", "amount": 60})["id"] == "r2"
    state = builders["B09"]()
    assert service.cancel_order(state, {"order_id": "o3", "reason": "no longer needed"}) == {}
    assert "order" in service.cancel_order(state, {"order_id": "o3", "reason": "no longer needed"})
    # Offsets: o2 is the newest instant though o3 sorts later as text and the listing ends with o3.
    offsets = builders["B05"]()
    assert service.newest_order_id(offsets) == "o2"
    assert service.validate(offsets) == []
    assert [o["id"] for o in service.list_orders(offsets, {"customer_id": "c1"})["orders"]] == [
        "o1",
        "o2",
        "o3",
    ]


def test_the_returned_agent_lists_the_shop_tools_through_the_runner_config(tmp_path: Path) -> None:
    """--check-mcp needs no model or key: it connects with the config the runner wrote."""
    command = f'"{sys.executable}" "{SHOP / "shop_agent.py"}" --check-mcp'
    report = run_scenario(
        scenario_ref=REF,
        agent_command=command,
        output_dir=tmp_path / "out",
        worlds="fixed",
        only=["W0_baseline"],
        k=1,
        trust_code=True,
        timeout_seconds=120,
    )
    run = next(r for r in report.cases[0].extensions["mcp"]["runs"] if r["world_id"] != "baseline")
    assert (run["run_status"], run["exit_code"], run["tool_calls"]) == ("COMPLETED", 0, 0)
    log = (tmp_path / "out" / run["run_dir"] / "agent.log").read_text(encoding="utf-8")
    assert log.splitlines()[0] == (
        "find_customer: Find customers by exact name and ZIP code. Returns every match."
    )
    assert [line.split(":")[0] for line in log.splitlines()] == [
        "find_customer",
        "list_orders",
        "get_order",
        "cancel_order",
        "refund",
    ]
    assert "Refund an amount against a payment. By default the money goes back" in log
    assert report.cases[0].extensions["mcp"]["subject"] is None  # --check-mcp writes no transcript
