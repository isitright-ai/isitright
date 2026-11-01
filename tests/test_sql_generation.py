"""Generation in the SQL pack: base states, imported domain hints, and the generic families.

These tests carry the assertions of the earlier generation tests (shared synthetic states,
CHECK and JSON Schema hints, composite-key fallback, declared widths) to the entity-model design.
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from isitright.core.constraints import OneOf, Range, ValidityStatus
from isitright.core.families import default_mutators
from isitright.core.families._util import fresh_key
from isitright.core.mutations import World
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.world import State
from isitright.packs.sql import hints as _hints  # noqa: F401
from isitright.packs.sql.analysis import (
    QueryGuidance,
    harvest_query_guidance,
    validate_read_only_query,
)
from isitright.packs.sql.hints import hints_from_guidance
from isitright.packs.sql.hosts import DuckdbHost, PostgresHost, SqliteHost
from isitright.packs.sql.mapping import (
    build_model,
    domain_value,
    fallback_base_state,
    generate_base_state,
    import_json_schema,
    import_sql_checks,
    to_database_state,
    to_state,
)
from isitright.packs.sql.postgres_ddl import Schema, parse_postgres_database_schema
from isitright.packs.sql.sqlite_schema import introspect_schema, parse_declared_type


def _sqlite_model(ddl: str) -> Any:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(ddl)
        return build_model(introspect_schema(connection), "sqlite")


def _guidance(**kwargs: Any) -> QueryGuidance:
    defaults: dict[str, Any] = {
        "tables": frozenset({"item"}),
        "columns": frozenset(),
        "literals": (),
        "has_distinct": False,
        "has_join": False,
        "has_filter": True,
        "has_aggregate": False,
    }
    return QueryGuidance(**{**defaults, **kwargs})


def _proposals(model: Any, base: Any, guidance: QueryGuidance, constraints: list[Any]) -> list[Any]:
    spec = WorldSpec("t", model.schema, constraints=[*model.constraints, *constraints])
    hints = hints_from_guidance(model, guidance)
    world = World(to_state(model, base))
    return [
        m
        for mutator in default_mutators(insert_variants=True)
        for m in mutator.propose(spec, world, hints)
    ]


# --- JSON Schema and CHECK hints (the 0.1 `_domain_value` and `_check_value` assertions) ----------


def _column_schema(facts: dict[str, Any]) -> dict[str, Any]:
    return {"properties": {"items": {"items": {"properties": {"value": facts}}}}}


def test_json_schema_facts_become_constraints_that_guide_generation() -> None:
    model = _sqlite_model("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    column = model.db.table("items").columns[1]

    def value(facts: dict[str, Any], ordinal: int) -> Any:
        (constraint,) = import_json_schema(model, _column_schema(facts))
        return domain_value(constraint.value_domain("items.value"), column, ordinal)

    assert value({"const": "fixed"}, 0) == "fixed"
    assert value({"enum": [None, "a", "b"]}, 2) == "b"
    integer = _sqlite_model("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)")
    (rule,) = import_json_schema(integer, _column_schema({"type": "integer", "minimum": 5}))
    assert isinstance(rule, Range)
    assert (
        domain_value(rule.value_domain("items.value"), integer.db.table("items").columns[1], 1) == 6
    )
    real = _sqlite_model("CREATE TABLE items (id INTEGER PRIMARY KEY, value REAL)")
    (rule,) = import_json_schema(real, _column_schema({"type": "number", "minimum": 0.5}))
    assert (
        domain_value(rule.value_domain("items.value"), real.db.table("items").columns[1], 1) == 1.5
    )
    assert import_json_schema(model, {}) == []


def test_sql_check_forms_become_generation_hints_and_unknown_forms_are_ignored() -> None:
    model = _sqlite_model(
        "CREATE TABLE item (id INTEGER PRIMARY KEY, "
        "status TEXT CHECK (status IN ('queued','done')),"
        " active INTEGER CHECK (active IN (0, 1)), amount REAL CHECK (amount >= 0.5),"
        " other INTEGER CHECK (other < 10))"
    )
    rules = {c.path: c for c in import_sql_checks(model)}
    assert isinstance(rules["item.status"], OneOf) and rules["item.status"].values == [
        "queued",
        "done",
    ]
    assert isinstance(rules["item.active"], OneOf) and rules["item.active"].values == [0, 1]
    assert isinstance(rules["item.amount"], Range) and rules["item.amount"].min == 0.5
    assert "item.other" not in rules


def test_generated_keys_stay_readable_and_unique() -> None:
    state = State({"t": ({"id": "id0"},)}, {"t": "id"})
    assert fresh_key(state, "t", "id0", set()) == "id1"
    assert fresh_key(state, "t", "abc", set()) == "abd"  # letters step, so patterns still match
    assert fresh_key(State({"t": ({"id": "AAA"},)}, {"t": "id"}), "t", "AAA", set()) == "AAB"
    assert fresh_key(State({"t": ({"id": "x-"},)}, {"t": "id"}), "t", "x-", set()) == "x-_1"
    assert fresh_key(State({"t": ({"id": 3},)}, {"t": "id"}), "t", 3, set()) == 4


# --- base states (the 0.2 shared synthetic states) ------------------------------------------------


def test_both_engines_share_the_same_generated_states_and_families() -> None:
    ddl = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected INTEGER)"
    sqlite_model = _sqlite_model(ddl)
    postgres_model = build_model(parse_postgres_database_schema(ddl), "postgres")
    guidance = harvest_query_guidance(
        validate_read_only_query("SELECT SUM(amount - collected) FROM item WHERE amount > 100"),
        validate_read_only_query(
            "SELECT SUM(amount) - SUM(collected) FROM item WHERE amount >= 100"
        ),
    )
    base_a = generate_base_state(sqlite_model, [])
    base_b = generate_base_state(postgres_model, [])
    assert base_a == base_b and base_a is not None
    families = {m.family for m in _proposals(sqlite_model, base_a, guidance, [])}
    assert families >= {"boundary", "missing", "duplicate"}
    assert {m.description for m in _proposals(sqlite_model, base_a, guidance, [])} == {
        m.description for m in _proposals(postgres_model, base_b, guidance, [])
    }


def test_an_unsupported_schema_has_no_strict_base_state_and_is_not_silently_weakened() -> None:
    model = _sqlite_model("CREATE TABLE item (id INTEGER PRIMARY KEY, title BLOB)")
    assert generate_base_state(model, []) is None


def test_base_states_cover_every_shared_type_and_bind_in_sqlite() -> None:
    ddl = (
        "CREATE TABLE item (id BIGINT PRIMARY KEY, amount DECIMAL, "
        "flag BOOLEAN, day DATE, score REAL)"
    )
    model = _sqlite_model(ddl)
    base = generate_base_state(model, [])
    assert base is not None
    left, right = SqliteHost(model.db).run_pair(
        base, "SELECT * FROM item", "SELECT * FROM item", timeout_seconds=5, max_result_rows=10
    )
    assert left == right and len(left.rows) == 1


def test_parameterised_types_use_generated_states_within_declared_widths() -> None:
    ddl = (
        "CREATE TABLE item (id VARCHAR(4) PRIMARY KEY, amount DECIMAL(10, 2), "
        "label VARCHAR(3) NOT NULL)"
    )
    model = _sqlite_model(ddl)
    base = generate_base_state(model, [])
    assert base is not None
    row = dict(zip(base.tables[0].columns, base.tables[0].rows[0], strict=True))
    assert len(str(row["label"])) <= 3 and len(str(row["id"])) <= 4
    SqliteHost(model.db).run_pair(
        base, "SELECT 1", "SELECT 1", timeout_seconds=5, max_result_rows=10
    )


def test_check_constraints_and_text_literals_steer_boundaries_and_filters() -> None:
    model = _sqlite_model(
        "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER CHECK (amount >= 5), tag TEXT)"
    )
    checks = import_sql_checks(model)
    base = generate_base_state(model, checks)
    assert base is not None and base.tables[0].rows == ((1, 6, None),)
    guidance = _guidance(
        columns=frozenset({("item", "amount"), ("item", "tag")}), literals=("x", 7)
    )
    descriptions = [m.description for m in _proposals(model, base, guidance, checks)]
    assert any("amount = 7" in d for d in descriptions) and any(
        "amount = 8" in d for d in descriptions
    )
    assert any("tag = 'x'" in d for d in descriptions)


def test_composite_keys_use_the_lenient_fallback_in_sqlite() -> None:
    model = _sqlite_model(
        "CREATE TABLE item (a INTEGER, b INTEGER, amount INTEGER, PRIMARY KEY (a, b))"
    )
    assert generate_base_state(model, []) is None
    base = fallback_base_state(model, [])
    assert len(base.tables[0].rows) == 1
    SqliteHost(model.db).run_pair(
        base, "SELECT 1", "SELECT 1", timeout_seconds=5, max_result_rows=10
    )
    guidance = _guidance(
        columns=frozenset({("item", "amount")}), literals=(100,), has_distinct=True
    )
    families = {m.family for m in _proposals(model, base, guidance, [])}
    assert families >= {"boundary", "duplicate"}


def test_a_null_variant_is_proposed_even_when_the_base_value_is_already_null() -> None:
    model = _sqlite_model("CREATE TABLE item (id INTEGER PRIMARY KEY, tag TEXT)")
    base = generate_base_state(model, [])
    assert base is not None and base.tables[0].rows == ((1, None),)
    guidance = _guidance(columns=frozenset({("item", "tag")}), literals=("a",))
    nulls = [m for m in _proposals(model, base, guidance, []) if m.family == "missing"]
    assert nulls and nulls[0].edits[0].entity["tag"] is None  # type: ignore[union-attr]


def test_sqlite_type_parameters_are_parsed_and_normalized() -> None:
    assert parse_declared_type("VARCHAR(10)") == ("TEXT", (10,))
    assert parse_declared_type("character varying (3)") == ("TEXT", (3,))
    assert parse_declared_type("CHAR") == ("TEXT", ())
    assert parse_declared_type("NUMERIC(10, 2)") == ("DECIMAL", (10, 2))
    assert parse_declared_type("DECIMAL(5)") == ("DECIMAL", (5,))
    assert parse_declared_type("VARCHAR(0)") == ("VARCHAR(0)", ())
    assert parse_declared_type("DECIMAL(2, 5)") == ("DECIMAL(2, 5)", ())
    assert parse_declared_type("INTEGER") == ("INTEGER", ())
    assert parse_declared_type("") == ("", ())


# --- state mapping --------------------------------------------------------------------------------


def test_states_round_trip_through_the_entity_model_including_blobs_and_decimals() -> None:
    ddl = "CREATE TABLE t (id INTEGER PRIMARY KEY, price DECIMAL, raw BLOB)"
    model = build_model(
        parse_postgres_database_schema("CREATE TABLE t (id INTEGER PRIMARY KEY, price DECIMAL)"),
        "postgres",
    )
    from decimal import Decimal

    from isitright.packs.sql.state import DatabaseState, TableState

    data = DatabaseState((TableState("t", ("id", "price"), ((1, Decimal("1.50")),)),))
    state = to_state(model, data)
    assert state.entities("t")[0]["price"] == "1.50"
    assert to_database_state(model, state) == data
    sqlite_model = _sqlite_model(ddl)
    blobs = DatabaseState((TableState("t", ("id", "price", "raw"), ((1, 2, b"\x00\x01"),)),))
    assert to_database_state(sqlite_model, to_state(sqlite_model, blobs)) == blobs


def test_tables_without_a_single_key_get_a_synthetic_row_key() -> None:
    model = _sqlite_model("CREATE TABLE log (msg TEXT)")
    from isitright.packs.sql.state import DatabaseState, TableState

    data = DatabaseState((TableState("log", ("msg",), (("a",), ("a",))),))
    state = to_state(model, data)
    assert [e["__row"] for e in state.entities("log")] == [1, 2]
    assert to_database_state(model, state) == data


def test_search_composes_generated_states_in_all_three_engines_models() -> None:
    ddl = "CREATE TABLE item (id INTEGER PRIMARY KEY, amount INTEGER, collected INTEGER)"
    for model in (
        _sqlite_model(ddl),
        build_model(parse_postgres_database_schema(ddl), "postgres"),
    ):
        base = generate_base_state(model, [])
        assert base is not None
        spec = WorldSpec("t", model.schema, constraints=model.constraints)
        guidance = _guidance(columns=frozenset({("item", "collected")}))
        found = search(
            spec,
            World(to_state(model, base)),
            hints_from_guidance(model, guidance),
            default_mutators(insert_variants=True),
            lambda c, _v: Evaluation(
                Verdict.DISAGREE
                if sum(1 for e in c.world.state.entities("item") if e["collected"] is None) == 1
                and len(c.world.state.entities("item")) >= 2
                else Verdict.AGREE
            ),
            budget=Budget(attempts=100),
        )
        assert found.findings
        assert spec.validate(found.findings[0].candidate.world.state).status is ValidityStatus.VALID


def test_host_fidelity_is_explicit() -> None:
    ddl = "CREATE TABLE item (id INTEGER PRIMARY KEY)"
    schema = Schema(parse_postgres_database_schema(ddl))
    assert SqliteHost(_sqlite_model(ddl).db).fidelity.value == "NATIVE_ISOLATED"
    assert PostgresHost(schema).fidelity.value == "NATIVE_ISOLATED"
    assert DuckdbHost(schema).fidelity.value == "EMULATED"


def test_run_pair_executes_in_order_and_stops_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from isitright.packs.sql import hosts
    from isitright.packs.sql.sqlite_sandbox import QueryExecutionError
    from isitright.packs.sql.state import DatabaseState, TableState

    model = _sqlite_model("CREATE TABLE item (id INTEGER PRIMARY KEY)")
    seen: list[str] = []
    real = hosts.execute_query

    def spy(connection: Any, sql: str, **kwargs: Any) -> Any:
        seen.append(sql)
        return real(connection, sql, **kwargs)

    monkeypatch.setattr(hosts, "execute_query", spy)
    state = DatabaseState((TableState("item", ("id",), ()),))
    host = SqliteHost(model.db)
    host.run_pair(state, "SELECT 1", "SELECT 2", timeout_seconds=5, max_result_rows=10)
    assert seen == ["SELECT 1", "SELECT 2"]
    seen.clear()
    with pytest.raises(QueryExecutionError):
        host.run_pair(
            state, "SELECT * FROM nope", "SELECT 3", timeout_seconds=5, max_result_rows=10
        )
    assert seen == ["SELECT * FROM nope"]


def test_a_literal_is_paired_only_with_the_columns_the_query_compares_it_with() -> None:
    model = _sqlite_model("CREATE TABLE t (id INTEGER PRIMARY KEY, kind TEXT, born TEXT);")
    sql = "SELECT COUNT(*) FROM t WHERE kind = 'VYBER' AND STRFTIME('%Y', born) >= '2012'"
    guidance = harvest_query_guidance(validate_read_only_query(sql))
    names = {h.name for h in hints_from_guidance(model, guidance).of("literal")}
    assert names == {"literal:t.kind='VYBER'", "literal:t.born='2012'"}
