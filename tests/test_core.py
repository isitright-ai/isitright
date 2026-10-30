"""Core primitives on a toy shop: entities, constraints, hints, families, search, minimization."""

from __future__ import annotations

from typing import Any

import pytest

from isitright.core.constraints import (
    Aggregate,
    ExprEnv,
    Expression,
    NotNull,
    OneOf,
    PythonConstraint,
    Range,
    RowExpr,
    Unique,
    ValidityStatus,
    ValidityTier,
    constraints_from_json,
    constraints_to_json,
)
from isitright.core.entities import (
    CollectionSpec,
    EntitySchema,
    FieldSpec,
    ModelError,
    RefSpec,
)
from isitright.core.families import default_mutators
from isitright.core.hints import (
    HINT_KINDS,
    Hint,
    HintKind,
    Hints,
    Provenance,
    hints_from_json,
    register_hint_kind,
)
from isitright.core.minimize import ddmin, minimize_path, minimize_world
from isitright.core.mutations import (
    Edit,
    Mutation,
    SetField,
    World,
    apply_edits,
    edits_between,
    edits_from_json,
    edits_to_json,
)
from isitright.core.oracles import Outcome
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.spec import Operation, ParamSpec, ToolSpec, WorldSpec
from isitright.core.stochastic import (
    Budget,
    RunOutcome,
    count,
    mcnemar_exact,
    rate_claim,
    run_repeated,
    stability,
)
from isitright.core.subjects import Cost
from isitright.core.world import State, diff_states


def schema() -> EntitySchema:
    return EntitySchema(
        collections=[
            CollectionSpec(
                name="customers",
                key="id",
                fields=[
                    FieldSpec(name="id"),
                    FieldSpec(name="name"),
                    FieldSpec(name="zip"),
                    FieldSpec(name="email", nullable=True),
                ],
                embedded=[
                    CollectionSpec(
                        name="methods",
                        key="id",
                        fields=[
                            FieldSpec(name="id"),
                            FieldSpec(name="type", enum=["card", "gift"]),
                        ],
                    )
                ],
            ),
            CollectionSpec(
                name="orders",
                key="id",
                fields=[
                    FieldSpec(name="id"),
                    FieldSpec(name="customer_id"),
                    FieldSpec(name="status", enum=["pending", "processing", "shipped"]),
                    FieldSpec(name="created_at", type="datetime"),
                    FieldSpec(name="total", type="float"),
                ],
                references=[RefSpec(field="customer_id", to="customers")],
            ),
            CollectionSpec(
                name="payments",
                key="id",
                fields=[
                    FieldSpec(name="id"),
                    FieldSpec(name="order_id"),
                    FieldSpec(name="method_id"),
                    FieldSpec(name="amount", type="float"),
                ],
                references=[
                    RefSpec(field="order_id", to="orders", owned=True),
                    RefSpec(field="method_id", to="customers.methods", enforced=False),
                ],
            ),
        ]
    )


def base_state() -> State:
    return State(
        {
            "customers": (
                {
                    "id": "c1",
                    "name": "Ana",
                    "zip": "10027",
                    "email": "a@x",
                    "methods": {
                        "m1": {"id": "m1", "type": "card"},
                        "m2": {"id": "m2", "type": "gift"},
                    },
                },
                {"id": "c2", "name": "Bo", "zip": "94110", "email": None, "methods": {}},
            ),
            "orders": (
                {
                    "id": "o1",
                    "customer_id": "c1",
                    "status": "shipped",
                    "created_at": "2024-05-01T10:00:00Z",
                    "total": 40.0,
                },
                {
                    "id": "o2",
                    "customer_id": "c1",
                    "status": "pending",
                    "created_at": "2024-05-28T10:00:00Z",
                    "total": 60.0,
                },
                {
                    "id": "o9",
                    "customer_id": "c2",
                    "status": "pending",
                    "created_at": "2024-05-29T09:00:00Z",
                    "total": 30.0,
                },
            ),
            "payments": (
                {"id": "p1", "order_id": "o1", "method_id": "m1", "amount": 40.0},
                {"id": "p2", "order_id": "o2", "method_id": "m2", "amount": 60.0},
                {"id": "p9", "order_id": "o9", "method_id": "m9", "amount": 30.0},
            ),
        },
        {"customers": "id", "orders": "id", "payments": "id"},
        {"now": "2024-06-01T12:00:00Z", "page_size": 10},
    )


def spec(**extra: Any) -> WorldSpec:
    return WorldSpec(
        id="toy",
        schema=schema(),
        constraints=[
            Aggregate(
                parent="orders",
                child="payments",
                via="order_id",
                child_field="amount",
                parent_field="total",
            ),
            RowExpr(collection="orders", expr="created_at <= @now"),
            Range(path="payments.amount", min=0, min_exclusive=True),
        ],
        params=[ParamSpec(name="max_page_size", values=[2])],
        tools=[
            ToolSpec(name="get_order", exposes=["orders.status", "payments.amount"]),
            ToolSpec(name="cancel", writes=True),
        ],
        **extra,
    )


def hints() -> Hints:
    return Hints(
        [
            Hint(
                kind="lookup",
                args={
                    "collection": "customers",
                    "fields": ["name", "zip"],
                    "value": ["Ana", "10027"],
                },
            ),
            Hint(kind="ordering", args={"collection": "orders", "field": "created_at"}),
            Hint(
                kind="gate",
                args={
                    "collection": "orders",
                    "field": "status",
                    "allows": ["pending"],
                    "action": "cancel",
                },
            ),
            Hint(kind="scope", args={"collection": "orders", "where": "customer_id in $lookup.id"}),
            Hint(
                kind="threshold",
                name="page",
                args={"collection": "orders", "count": 2, "where": "customer_id in $lookup.id"},
            ),
            Hint(kind="threshold", name="big", args={"path": "orders.total", "value": 100}),
        ]
    )


def world() -> World:
    return World(base_state())


# --- state and entities -------------------------------------------------------------------------


def test_state_is_serializable_fingerprintable_and_diffable() -> None:
    state = base_state()
    assert State.from_json(state.to_json()).fingerprint() == state.fingerprint()
    smaller = state.without([("payments", "p9")])
    assert smaller.size() == state.size() - 1 and smaller.fingerprint() != state.fingerprint()
    changed = apply_edits(
        state, [SetField(collection="orders", key="o2", path=["status"], value="shipped")]
    )
    diff = diff_states(state, changed)
    assert diff["changed"][0]["fields"]["status"]["after"] == "shipped"
    assert state.get(("orders", "o2")) is not None and state.get(("orders", "zz")) is None


def test_structural_checks_find_each_kind_of_problem() -> None:
    model = schema()
    assert model.check_structural(base_state()) == []
    bad = base_state().mutable()
    bad["orders"][0]["status"] = "weird"
    bad["orders"][1]["customer_id"] = "nobody"
    bad["orders"][2]["total"] = None
    bad["orders"].append(dict(bad["orders"][0]))
    problems = " | ".join(
        model.check_structural(State({k: tuple(v) for k, v in bad.items()}, base_state().keys))
    )
    for fragment in ("is not one of", "references a missing", "is null", "duplicate key"):
        assert fragment in problems


def test_paths_resolve_or_raise() -> None:
    model = schema()
    assert model.resolve("customers.methods.type")[1].enum == ["card", "gift"]
    for bad in ("orders", "orders.nope", "customers.nope.type", "ghost.id"):
        with pytest.raises(ModelError):
            model.resolve(bad)


def test_cluster_follows_owned_references() -> None:
    state = base_state()
    assert schema().cluster(state, ("orders", "o2")) == {("orders", "o2"), ("payments", "p2")}


# --- constraints --------------------------------------------------------------------------------


def test_the_spec_is_valid_and_tiers_are_reported() -> None:
    validity = spec().validate(base_state())
    assert validity.status is ValidityStatus.VALID
    assert validity.tiers == (ValidityTier.STRUCTURAL, ValidityTier.DOMAIN_VALIDATED)
    assert (
        spec().validate(base_state().without([("payments", "p9")])).status is ValidityStatus.INVALID
    )


def test_aggregate_and_row_constraints_reject_broken_states() -> None:
    state = apply_edits(
        base_state(),
        [
            SetField(collection="payments", key="p2", path=["amount"], value=59.0),
            SetField(
                collection="orders", key="o1", path=["created_at"], value="2025-01-01T00:00:00Z"
            ),
        ],
    )
    problems = " | ".join(spec().validate(state).problems)
    assert "sum of payments.amount is 59" in problems and "violates created_at <= @now" in problems


def test_other_constraint_kinds() -> None:
    model, state = schema(), base_state()
    assert NotNull(path="customers.email").check(model, state)
    assert OneOf(path="orders.status", values=["pending"]).check(model, state)
    assert Unique(collection="orders", fields=["customer_id"]).check(model, state) is not False
    assert Range(path="orders.total", max=50).check(model, state)
    assert Range(path="orders.created_at", max="2024-05-02T00:00:00Z").check(model, state)
    assert OneOf(path="customers.methods.type", values=["card"]).check(model, state)


def test_python_constraints_are_check_only_and_listed() -> None:
    rule = PythonConstraint("no_c2", lambda s: ["c2 present"] if s.get(("customers", "c2")) else [])
    verdict = spec(python_constraints=[rule]).validate(base_state())
    assert verdict.status is ValidityStatus.INVALID and verdict.check_only_rules == ("no_c2",)


def test_constraints_round_trip_through_json() -> None:
    rules = spec().constraints
    assert constraints_from_json(constraints_to_json(rules)) == rules


def test_a_constraint_naming_a_missing_field_is_rejected_at_load() -> None:
    with pytest.raises(ModelError, match="no field 'nope'"):
        WorldSpec(id="x", schema=schema(), constraints=[Range(path="orders.nope", min=0)])


def test_expressions_use_fields_params_and_hints() -> None:
    model = schema().collection("orders")
    row = base_state().entities("orders")[1]
    env = ExprEnv(model, {"now": "2024-06-01T12:00:00Z"}, {"lookup": [{"id": "c1"}]})
    assert Expression("status == 'pending' and created_at < @now").holds(row, env)
    assert Expression("customer_id in $lookup.id").holds(row, env)
    assert Expression("total / 2 == 30").holds(row, env)
    assert Expression("lower(status) == 'pending'").names() == {"status"}
    assert not Expression("customer_id == 'zz'").holds(row, env)
    for bad in ("__import__('os')", "a[0]", "x if y else z"):
        with pytest.raises(ModelError):
            Expression(bad)


# --- hints --------------------------------------------------------------------------------------


def test_hints_validate_against_the_model() -> None:
    hints().validate(schema())
    with pytest.raises(ModelError, match="no field 'zipp'"):
        Hints(
            [
                Hint(
                    kind="lookup",
                    args={"collection": "customers", "fields": ["zipp"], "value": ["1"]},
                )
            ]
        ).validate(schema())
    with pytest.raises(ModelError, match="unknown hint kind"):
        Hints([Hint(kind="mystery")]).validate(schema())
    with pytest.raises(ModelError, match="unknown hint \\$ghost"):
        Hints(
            [Hint(kind="scope", args={"collection": "orders", "where": "customer_id in $ghost.id"})]
        ).validate(schema())


def test_hint_kinds_are_registered_like_built_ins() -> None:
    register_hint_kind(HintKind("custom", lambda _s, _h: None))
    assert "custom" in HINT_KINDS
    Hints([Hint(kind="custom")]).validate(schema())
    del HINT_KINDS["custom"]


def test_hints_merge_and_parse() -> None:
    shared = Hints(
        [
            Hint(
                kind="gate",
                name="g",
                args={"collection": "orders", "field": "status", "allows": ["a"]},
            )
        ]
    )
    merged = shared.merged(
        [
            Hint(
                kind="gate",
                name="g",
                args={"collection": "orders", "field": "status", "allows": ["b"]},
            )
        ]
    )
    assert merged.get("g") is not None and merged.get("g").args["allows"] == ["b"]  # type: ignore[union-attr]
    parsed = hints_from_json({"ordering": {"collection": "orders", "field": "created_at"}})
    assert parsed[0].provenance is Provenance.DECLARED and parsed[0].name == "ordering"
    listed = hints_from_json(
        [{"kind": "gate", "name": "x", "provenance": "harvested:trace", "collection": "o"}]
    )
    assert listed[0].provenance is Provenance.HARVESTED_TRACE


def test_scope_uses_the_lookup() -> None:
    h = hints()
    scope = h.get("scope")
    assert scope is not None
    assert {e["id"] for e in h.scoped(schema(), base_state(), scope)} == {"o1", "o2"}


# --- mutations and families ---------------------------------------------------------------------


def test_edits_round_trip_and_apply() -> None:
    edits: list[Edit] = [SetField(collection="orders", key="o1", path=["status"], value="pending")]
    assert edits_from_json(edits_to_json(edits)) == edits
    after = apply_edits(base_state(), edits)
    assert edits_between(base_state(), after) == edits


def families() -> dict[str, list[Mutation]]:
    out: dict[str, list[Mutation]] = {}
    for mutator in default_mutators():
        out[mutator.family] = list(mutator.propose(spec(), world(), hints()))
    return out


def test_each_generic_family_proposes_for_the_toy_shop() -> None:
    found = families()
    for family in (
        "boundary",
        "missing",
        "key_collision",
        "duplicate",
        "tie",
        "empty",
        "dangling",
        "cardinality_boundary",
        "split",
        "representation",
        "out_of_scope_extreme",
        "temporal",
        "units_scale",
        "service_parameter",
    ):
        assert found[family], family
    assert not found["prior_operation"] and not found["timing"]


def test_hinted_mutations_carry_the_hints_that_led_to_them() -> None:
    found = families()
    collision = found["key_collision"]
    assert all(m.hints == ["lookup"] for m in collision)
    assert {m.description.split(":")[0].split(" ")[0] for m in collision}
    assert any("gate" in m.hints for m in found["boundary"])


def test_generic_families_keep_aggregate_constraints_intact() -> None:
    s = spec()
    valid = invalid = 0
    for mutations in families().values():
        for mutation in mutations:
            if mutation.target != "state":
                continue
            result = s.validate(world().apply(mutation).state)
            valid += result.status is ValidityStatus.VALID
            invalid += result.status is ValidityStatus.INVALID
    assert valid > 20 and invalid > 0  # duplicates copy clusters; dangling hard refs are rejected


def test_split_makes_two_payments_summing_to_the_total() -> None:
    split = families()["split"][0]
    state = world().apply(split).state
    assert spec().validate(state).status is ValidityStatus.VALID
    assert len([p for p in state.entities("payments") if p["order_id"] in {"o1", "o2"}]) == 3


def test_cardinality_boundary_pads_with_older_orders() -> None:
    mutation = families()["cardinality_boundary"][0]
    state = world().apply(mutation).state
    own = [o for o in state.entities("orders") if o["customer_id"] == "c1"]
    assert len(own) == 3  # count + 1 would be 3, count itself is already met
    assert max(o["created_at"] for o in own) == "2024-05-28T10:00:00Z"


def test_representation_makes_text_order_disagree_with_instant_order() -> None:
    mutation = families()["representation"][0]
    value = mutation.edits[0].value  # type: ignore[union-attr]
    assert value < "2024-05-28T10:00:00Z" and value.endswith(":00") and "-" in value[-6:]


def test_unobservable_changes_are_flagged_by_the_fields_they_touch() -> None:
    assert spec().exposed_paths() == {"orders.status", "payments.amount"}


def test_prior_operation_builds_reachable_states() -> None:
    def options(state: State) -> Any:
        for order in state.entities("orders"):
            yield {"order_id": order["id"]}

    def apply(state: State, args: dict[str, Any]) -> State | None:
        return apply_edits(
            state,
            [SetField(collection="orders", key=args["order_id"], path=["status"], value="shipped")],
        )

    operation = Operation("ship", options, apply, lambda a: [("orders", a["order_id"])])
    mutations = list(
        next(m for m in default_mutators() if m.family == "prior_operation").propose(
            spec(operations=[operation]), world(), hints()
        )
    )
    assert mutations and all(m.reachable for m in mutations)
    assert {m.atoms[0][1] for m in mutations if m.hints} == {"o2"}  # o1 is already shipped


def test_response_and_timing_mutations() -> None:
    s = spec()
    s.tools[0].nested_lists = ["payments"]
    s.tools[0].list_field = "orders"
    trace = Hint(
        kind="trace",
        provenance=Provenance.HARVESTED_TRACE,
        args={"calls": [{"tool": "get_order", "arguments": {"order_id": "o2"}}]},
    )
    all_hints = hints().merged([trace])
    by_family = {m.family: list(m.propose(s, world(), all_hints)) for m in default_mutators()}
    responses = by_family["response_edit"]
    assert {m.response.op for m in responses if m.response} == {
        "reorder",
        "drop_field",
        "empty_ack",
    }
    timing = by_family["timing"]
    assert timing and timing[0].trigger is not None and timing[0].trigger.tool == "get_order"
    applied = world().apply(timing[0])
    assert applied.timers and applied.state == world().state
    assert World.from_json(applied.to_json()).fingerprint() == applied.fingerprint()


# --- search -------------------------------------------------------------------------------------


def _diverges_when(world_: World) -> bool:
    """A composed bug: the newest order is not pending while an older one still is."""
    own = sorted(
        (o for o in world_.state.entities("orders") if o["customer_id"] == "c1"),
        key=lambda o: o["created_at"],
    )
    return (
        len(own) > 1
        and own[-1]["status"] != "pending"
        and any(o["status"] == "pending" for o in own[:-1])
    )


def _evaluate(candidate: Any, _validity: Any) -> Evaluation:
    return Evaluation(Verdict.DISAGREE if _diverges_when(candidate.world) else Verdict.AGREE)


def test_search_finds_a_depth_two_disagreement_and_accounts_for_the_budget() -> None:
    result = search(
        spec(),
        world(),
        hints(),
        default_mutators(),
        _evaluate,
        budget=Budget(attempts=4000),
        seed=3,
    )
    assert result.findings
    finding = result.findings[0]
    assert len(finding.candidate.world.path) == 2
    families = {m.family for m in finding.candidate.world.path}
    assert "boundary" in families and families <= {"boundary", "duplicate"}
    account = result.accounting()
    assert account["depth_reached"] == 2 and account["budget_by_group"]["hinted"]["executed"] > 0
    assert account["rejected"].get("domain_constraint", 0) > 0
    assert "stopped at the first valid disagreement" in account["notes"]
    assert "prior_operation" in account["families_skipped"]


def test_search_is_deterministic_for_a_seed_and_respects_the_attempt_budget() -> None:
    def run(seed: int, attempts: int) -> list[str]:
        r = search(
            spec(), world(), hints(), default_mutators(), _evaluate,
            budget=Budget(attempts=attempts), seed=seed,
        )  # fmt: skip
        return [f.candidate.world.fingerprint() for f in r.findings] + [str(r.attempts)]

    assert run(1, 4000) == run(1, 4000)
    assert 0 < int(run(1, 5)[-1]) <= 5  # the budget is a cap on candidates visited
    none = search(
        spec(), world(), hints(), default_mutators(), lambda *_: Evaluation(Verdict.AGREE),
        budget=Budget(attempts=60), seed=0,
    )  # fmt: skip
    assert not none.findings and none.accounting()["budget"]["stopped_by"] == "attempts"


def test_composition_from_all_collects_every_depth_two_world() -> None:
    result = search(
        spec(), world(), hints(), default_mutators(), _evaluate,
        budget=Budget(attempts=3000), stop_on_first=False, compose_from="all",
    )  # fmt: skip
    assert len(result.findings) > 1


# --- minimization -------------------------------------------------------------------------------


def test_ddmin_reduces_to_the_needed_entries() -> None:
    reduction = ddmin(list(range(20)), max_attempts=200, accepts=lambda kept: {3, 11} <= set(kept))
    assert sorted(reduction.kept) == [3, 11] and reduction.complete
    capped = ddmin(list(range(20)), max_attempts=1, accepts=lambda kept: {3} <= set(kept))
    assert not capped.complete


def test_minimize_world_keeps_clusters_whole_and_reverts_toward_base() -> None:
    s, base = spec(), base_state()
    mutated = apply_edits(
        base,
        [
            SetField(collection="orders", key="o2", path=["status"], value="shipped"),
            SetField(collection="customers", key="c2", path=["name"], value="Zed"),
        ],
    )

    def reproduces(w: World) -> bool:
        order = w.state.get(("orders", "o2"))
        return order is not None and order["status"] == "shipped"

    result = minimize_world(
        s, World(mutated), base, reproduces, referenced=["orders", "payments", "customers"]
    )
    kept = {a for a in result.world.state.atoms()}
    assert ("orders", "o2") in kept and ("payments", "p2") in kept
    assert result.atoms_after < result.atoms_before and result.changed_atoms == 1
    assert spec().validate(result.world.state).status is ValidityStatus.VALID


def test_minimize_path_drops_unneeded_mutations() -> None:
    a = Mutation(
        family="a",
        description="a",
        edits=[SetField(collection="orders", key="o1", path=["total"], value=40.0)],
    )
    b = Mutation(
        family="b",
        description="b",
        edits=[SetField(collection="orders", key="o2", path=["status"], value="shipped")],
    )
    both = World(base_state()).apply(a).apply(b)
    reduced, _, trials = minimize_path(
        World(base_state()),
        both.path,
        lambda w: w.state.get(("orders", "o2"))["status"] == "shipped",  # type: ignore[index]
    )
    assert [m.family for m in reduced.path] == ["b"] and trials >= 1


# --- stochastic evaluation ----------------------------------------------------------------------


def _bad() -> RunOutcome:
    return RunOutcome(Outcome.NOT_MET)


def _good() -> RunOutcome:
    return RunOutcome(Outcome.MET)


def test_counts_and_flaky_baselines() -> None:
    counts = count(
        [_good(), _bad(), RunOutcome(Outcome.CANNOT_JUDGE), RunOutcome(None, error=True)]
    )
    assert (counts.n, counts.met, counts.not_met, counts.cannot_judge, counts.errors) == (
        4,
        1,
        1,
        1,
        1,
    )
    flaky = stability([_good(), _bad(), _good(), _good()], [_bad()] * 4, k=4)
    assert "flaky" in flaky.note and flaky.rate_claim is None


def test_no_rate_claim_without_enough_paired_runs() -> None:
    four = stability([_good()] * 4, [_bad()] * 4, k=4)
    assert four.rate_claim is None and "counts only" in four.note
    assert four.world is not None and four.world.not_met == 4


def test_a_rate_claim_needs_a_paired_test_and_names_it() -> None:
    claim = rate_claim([_good()] * 12, [_bad()] * 12)
    assert claim is not None and claim.test.startswith("exact McNemar") and claim.p_value < 0.001
    assert rate_claim([_good()] * 12, [_good()] * 12) is None
    assert rate_claim([_bad()] * 12, [_good()] * 12) is None
    assert mcnemar_exact(0, 0) == 1.0 and mcnemar_exact(1, 9) < 0.05


def test_run_repeated_stops_at_the_money_budget() -> None:
    budget = Budget(money=0.25)
    outcomes = run_repeated(lambda _t: RunOutcome(Outcome.MET, cost=Cost(money=0.1)), 10, budget)
    assert len(outcomes) == 3 and budget.exhausted == "money"
    assert budget.to_json()["spent"]["runs"] == 3  # type: ignore[index]
    assert not Budget(seconds=0.0).can_run() and not Budget(runs=0).can_run()
