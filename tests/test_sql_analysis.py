import pytest
import sqlglot

from isitright.packs.sql.analysis import (
    SqlStatement,
    SqlValidationError,
    harvest_query_guidance,
    validate_read_only_query,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH item AS (SELECT 1 AS value) SELECT value FROM item",
        "SELECT 1 UNION ALL SELECT 2",
    ],
)
def test_accepts_single_read_only_queries(sql: str) -> None:
    assert validate_read_only_query(sql).expression is not None


def test_detects_only_top_level_order_by() -> None:
    nested = validate_read_only_query("SELECT * FROM (SELECT 1 ORDER BY 1)")
    top_level = validate_read_only_query("SELECT 1 ORDER BY 1")
    assert nested.top_level_ordered is False
    assert top_level.top_level_ordered is True


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELECT 1; SELECT 2",
        "INSERT INTO items VALUES (1)",
        "UPDATE items SET value = 1",
        "DELETE FROM items",
        "DROP TABLE items",
        "PRAGMA table_info(items)",
        "ATTACH DATABASE 'other.sqlite' AS other",
        "VALUES (1)",
    ],
)
def test_rejects_non_select_or_multiple_statements(sql: str) -> None:
    with pytest.raises(SqlValidationError):
        validate_read_only_query(sql)


def test_rejects_malformed_sql() -> None:
    with pytest.raises(SqlValidationError, match="could not be parsed"):
        validate_read_only_query("SELECT (")


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
def test_shared_guidance_resolves_aliases_and_unqualified_columns(dialect: str) -> None:
    expression = sqlglot.parse_one(
        "SELECT c.name FROM customers AS c JOIN orders AS o ON c.id = o.customer_id "
        "WHERE amount > 10",
        read=dialect,
    )
    guidance = harvest_query_guidance(SqlStatement(expression, False))
    assert guidance.tables == {"customers", "orders"}
    assert guidance.has_join and guidance.has_filter
    assert guidance.references_column("customers", "name")
    assert not guidance.references_column("orders", "name")
    assert guidance.references_column("orders", "amount")
    assert guidance.references_column("customers", "amount")
