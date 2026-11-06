"""Warehouse DDL import: BigQuery, Presto/Trino and Hive forms, names, keys, partitions."""

from __future__ import annotations

import pytest

from isitright.packs.sql.dialects import get_dialect, resolve_dialect_and_engine
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.warehouse_ddl import TableResolver, parse_warehouse_schema

BQ = get_dialect("bigquery")
PRESTO = get_dialect("presto")

BQ_DDL = """
CREATE TABLE `proj-x.shop.orders` (
  id INT64 NOT NULL OPTIONS(description="the order id"),
  items ARRAY<STRUCT<sku STRING, qty INT64, tags ARRAY<STRING>>>,
  placed TIMESTAMP,
  PRIMARY KEY (id) NOT ENFORCED
)
PARTITION BY DATE(placed)
OPTIONS(description="orders");
"""


def test_bigquery_table_with_nested_columns_keys_partitions_and_descriptions() -> None:
    table = parse_warehouse_schema(BQ_DDL, BQ).tables[0]
    assert (table.name, table.qualified) == ("orders", "proj-x.shop.orders")
    assert table.partition_columns == ("placed",)
    assert table.declared_keys == (("id",),)
    assert table.description == "orders"
    by_name = {c.name: c for c in table.columns}
    assert by_name["id"].primary_key_position == 1 and by_name["id"].not_null
    assert by_name["id"].description == "the order id"
    assert by_name["items"].declared_type == "ARRAY"
    assert by_name["placed"].declared_type == "TIMESTAMPTZ"
    assert table.engine_ddl is not None and "STRUCT" in table.engine_ddl


def test_a_table_without_a_key_is_accepted_in_every_dialect() -> None:
    for dialect, ddl in (
        (BQ, "CREATE TABLE d.t (a INT64)"),
        (PRESTO, "CREATE TABLE web.t (a bigint)"),
        (PRESTO, "CREATE TABLE t (a BIGINT) PARTITIONED BY (ds STRING) STORED AS ORC"),
    ):
        table = parse_warehouse_schema(ddl, dialect).tables[0]
        assert not any(c.primary_key_position for c in table.columns)


def test_presto_partitioned_by_property_and_hive_partition_columns_become_columns() -> None:
    presto = parse_warehouse_schema(
        "CREATE TABLE hive.web.t (id bigint, ds varchar) WITH (partitioned_by = ARRAY['ds'])",
        PRESTO,
    ).tables[0]
    assert presto.partition_columns == ("ds",)
    hive = parse_warehouse_schema(
        "CREATE TABLE web.t (id BIGINT, m MAP<STRING,BIGINT>) PARTITIONED BY (ds STRING)",
        PRESTO,
    ).tables[0]
    assert [c.name for c in hive.columns] == ["id", "m", "ds"]
    assert hive.partition_columns == ("ds",)
    assert hive.columns[1].declared_type == "MAP"


def test_table_references_resolve_by_suffix_and_ambiguity_is_an_error() -> None:
    schema = parse_warehouse_schema(
        "CREATE TABLE `p.d1.t` (a INT64); CREATE TABLE `p.d2.t` (a INT64);"
        "CREATE TABLE `p.d1.u` (a INT64)",
        BQ,
    )
    assert [t.name for t in schema.tables] == ["d1_t", "d2_t", "u"]
    resolver = TableResolver(schema)
    assert resolver.find("d1.t") is not None and resolver.find("d1.t").name == "d1_t"  # type: ignore[union-attr]
    assert resolver.find("p.d1.u") is not None
    assert resolver.find("missing") is None
    with pytest.raises(SqlInputError, match="ambiguous"):
        resolver.find("t")


def test_unsupported_types_and_statements_are_rejected_naming_the_construct() -> None:
    with pytest.raises(SqlInputError, match="GEOGRAPHY"):
        parse_warehouse_schema("CREATE TABLE d.t (g GEOGRAPHY)", BQ)
    with pytest.raises(SqlInputError, match="BIGNUMERIC"):
        parse_warehouse_schema("CREATE TABLE d.t (g BIGNUMERIC)", BQ)
    with pytest.raises(SqlInputError, match="VIEW"):
        parse_warehouse_schema("CREATE VIEW d.v AS SELECT 1", BQ)
    with pytest.raises(SqlInputError, match="AS"):
        parse_warehouse_schema("CREATE TABLE d.t AS SELECT 1 AS a", BQ)
    with pytest.raises(SqlInputError, match="unknown column"):
        parse_warehouse_schema("CREATE TABLE d.t (a INT64, PRIMARY KEY (b) NOT ENFORCED)", BQ)


def test_declared_foreign_keys_are_soft_and_do_not_order_loading() -> None:
    schema = parse_warehouse_schema(
        "CREATE TABLE `p.d.a` (id INT64, b_id INT64, PRIMARY KEY (id) NOT ENFORCED,"
        " FOREIGN KEY (b_id) REFERENCES `p.d.b`(id) NOT ENFORCED);"
        "CREATE TABLE `p.d.b` (id INT64, a_id INT64, PRIMARY KEY (id) NOT ENFORCED,"
        " FOREIGN KEY (a_id) REFERENCES `p.d.a`(id) NOT ENFORCED)",
        BQ,
    )
    assert all(k.on_update == "NOT ENFORCED" for t in schema.tables for k in t.foreign_keys)
    assert {k.referenced_table for t in schema.tables for k in t.foreign_keys} == {"a", "b"}


def test_dialect_and_engine_resolution_keeps_the_old_meaning_of_engine() -> None:
    assert [d.name for d in (resolve_dialect_and_engine("duckdb", None)[0],)] == ["postgres"]
    assert resolve_dialect_and_engine(None, None)[1] == "sqlite"
    assert resolve_dialect_and_engine(None, "bigquery")[1] == "duckdb"
    assert resolve_dialect_and_engine("duckdb", "trino")[0].family == "presto"
    with pytest.raises(SqlInputError, match="cannot run on engine"):
        resolve_dialect_and_engine("postgres", "bigquery")
    with pytest.raises(SqlInputError, match="dialect must be"):
        resolve_dialect_and_engine(None, "oracle")
