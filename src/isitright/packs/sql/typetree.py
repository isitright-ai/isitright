"""Declared column types as a tree, so nested values load and render exactly.

A warehouse column can be a scalar or a nested type (`ARRAY`, `STRUCT`, `MAP`). The tree keeps the
declared type; the entity model sees a nested column as a `json` field whose `shape` (a JSON Schema
subset) says what values are valid for the dialect. State values are JSON-compatible: a struct is a
mapping, an array a list, a map a list of ``[key, value]`` pairs. Decimals are strings, dates and
timestamps ISO strings, bytes ``{"$bytes": base64}``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlglot import exp

from isitright.packs.sql.errors import SqlInputError

INTEGERS = {"TINYINT": 8, "SMALLINT": 16, "INTEGER": 32, "BIGINT": 64}
NESTED = frozenset({"ARRAY", "STRUCT", "MAP"})

_SCALARS: dict[exp.DataType.Type, str] = {
    exp.DataType.Type.TINYINT: "TINYINT",
    exp.DataType.Type.SMALLINT: "SMALLINT",
    exp.DataType.Type.INT: "INTEGER",
    exp.DataType.Type.BIGINT: "BIGINT",
    exp.DataType.Type.FLOAT: "REAL",
    exp.DataType.Type.DOUBLE: "DOUBLE",
    exp.DataType.Type.DECIMAL: "DECIMAL",
    exp.DataType.Type.VARCHAR: "TEXT",
    exp.DataType.Type.CHAR: "TEXT",
    exp.DataType.Type.TEXT: "TEXT",
    exp.DataType.Type.BOOLEAN: "BOOLEAN",
    exp.DataType.Type.DATE: "DATE",
    exp.DataType.Type.TIMESTAMP: "TIMESTAMP",
    exp.DataType.Type.TIMESTAMPTZ: "TIMESTAMPTZ",
    exp.DataType.Type.BINARY: "BYTES",
    exp.DataType.Type.VARBINARY: "BYTES",
}


@dataclass(frozen=True, slots=True)
class TypeNode:
    kind: str
    """A scalar kind (`BIGINT`, `DOUBLE`, `DECIMAL`, `TEXT`, `BOOLEAN`, `DATE`, `TIMESTAMP`,
    `TIMESTAMPTZ`, `BYTES`, ...) or `ARRAY`, `STRUCT`, `MAP`."""
    element: TypeNode | None = None
    fields: tuple[tuple[str, TypeNode, bool], ...] = ()
    """For a struct: ``(name, type, not_null)``."""
    key: TypeNode | None = None
    value: TypeNode | None = None
    precision: int | None = None
    scale: int | None = None

    @property
    def nested(self) -> bool:
        return self.kind in NESTED

    def paths(self, prefix: str = "") -> list[str]:
        """Every path inside this type: ``a``, ``a[*]``, ``a[*].b`` (the 0.5 JSON syntax)."""
        out: list[str] = []
        if self.kind == "ARRAY" and self.element is not None:
            out.append(prefix + "[*]")
            out.extend(self.element.paths(prefix + "[*]"))
        elif self.kind == "STRUCT":
            for name, inner, _ in self.fields:
                out.append(f"{prefix}.{name}")
                out.extend(inner.paths(f"{prefix}.{name}"))
        elif self.kind == "MAP" and self.key is not None and self.value is not None:
            out.append(prefix + "[*]")
        return out


def from_sqlglot(node: exp.DataType | None) -> TypeNode:
    """The type tree of a SQLGlot data type, or `SqlInputError` naming the unsupported type."""
    if node is None:
        raise SqlInputError("unsupported column type: none given")
    kind = node.this
    if kind == exp.DataType.Type.ARRAY:
        inner = node.expressions
        if len(inner) != 1 or not isinstance(inner[0], exp.DataType):
            raise SqlInputError("unsupported column type: ARRAY without an element type")
        return TypeNode("ARRAY", element=from_sqlglot(inner[0]))
    if kind in (exp.DataType.Type.STRUCT, exp.DataType.Type.OBJECT):
        fields = []
        for item in node.expressions:
            if isinstance(item, exp.ColumnDef):
                not_null = any(
                    isinstance(c.kind, exp.NotNullColumnConstraint) for c in item.constraints
                )
                fields.append((item.name, from_sqlglot(item.args.get("kind")), not_null))
            else:
                raise SqlInputError("unsupported column type: STRUCT field without a name")
        if not fields:
            raise SqlInputError("unsupported column type: STRUCT without fields")
        return TypeNode("STRUCT", fields=tuple(fields))
    if kind == exp.DataType.Type.MAP:
        inner = node.expressions
        if len(inner) != 2 or not all(isinstance(i, exp.DataType) for i in inner):
            raise SqlInputError("unsupported column type: MAP without key and value types")
        return TypeNode("MAP", key=from_sqlglot(inner[0]), value=from_sqlglot(inner[1]))
    if kind == exp.DataType.Type.BIGDECIMAL:
        raise SqlInputError("unsupported column type: BIGNUMERIC")
    if kind not in _SCALARS:
        name = node.sql() if hasattr(node, "sql") else str(kind)
        raise SqlInputError(f"unsupported column type: {name}")
    scalar = _SCALARS[kind]
    params = [
        int(p.this.this)
        for p in node.expressions
        if isinstance(p, exp.DataTypeParam) and isinstance(p.this, exp.Literal) and p.this.is_int
    ]
    if scalar == "DECIMAL":
        precision: int | None = 38
        scale: int | None = 9
        if len(params) == 1:
            precision, scale = params[0], 0
        elif len(params) >= 2:
            precision, scale = params[0], params[1]
        if precision is not None and precision > 38:
            raise SqlInputError("unsupported column type: DECIMAL wider than 38 digits")
        return TypeNode("DECIMAL", precision=precision, scale=scale)
    return TypeNode(scalar)


# --- engine type text ---------------------------------------------------------------------------


def duckdb_type(node: TypeNode) -> str:
    if node.kind == "ARRAY" and node.element is not None:
        return duckdb_type(node.element) + "[]"
    if node.kind == "STRUCT":
        inner = ", ".join(f'"{n}" {duckdb_type(t)}' for n, t, _ in node.fields)
        return f"STRUCT({inner})"
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        return f"MAP({duckdb_type(node.key)}, {duckdb_type(node.value)})"
    if node.kind == "DECIMAL":
        return f"DECIMAL({node.precision or 38}, {node.scale or 0})"
    return {"TEXT": "VARCHAR", "BYTES": "BLOB", "REAL": "FLOAT"}.get(node.kind, node.kind)


def bigquery_type(node: TypeNode) -> str:
    if node.kind == "ARRAY" and node.element is not None:
        return f"ARRAY<{bigquery_type(node.element)}>"
    if node.kind == "STRUCT":
        return "STRUCT<" + ", ".join(f"`{n}` {bigquery_type(t)}" for n, t, _ in node.fields) + ">"
    if node.kind == "MAP":
        raise SqlInputError("unsupported column type: MAP in BigQuery")
    if node.kind == "DECIMAL":
        if (node.precision, node.scale) in ((None, None), (38, 9)):
            return "NUMERIC"
        return f"NUMERIC({node.precision}, {node.scale or 0})"
    return {
        "TINYINT": "INT64",
        "SMALLINT": "INT64",
        "INTEGER": "INT64",
        "BIGINT": "INT64",
        "REAL": "FLOAT64",
        "DOUBLE": "FLOAT64",
        "TEXT": "STRING",
        "BOOLEAN": "BOOL",
        "DATE": "DATE",
        "TIMESTAMP": "DATETIME",
        "TIMESTAMPTZ": "TIMESTAMP",
        "BYTES": "BYTES",
    }[node.kind]


def presto_type(node: TypeNode) -> str:
    if node.kind == "ARRAY" and node.element is not None:
        return f"ARRAY({presto_type(node.element)})"
    if node.kind == "STRUCT":
        return "ROW(" + ", ".join(f'"{n}" {presto_type(t)}' for n, t, _ in node.fields) + ")"
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        return f"MAP({presto_type(node.key)}, {presto_type(node.value)})"
    if node.kind == "DECIMAL":
        return f"DECIMAL({node.precision or 38}, {node.scale or 0})"
    return {
        "TEXT": "VARCHAR",
        "BYTES": "VARBINARY",
        "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE",
    }.get(node.kind, node.kind)


# --- values ---------------------------------------------------------------------------------------


def _json_type(node: TypeNode) -> str:
    if node.kind in INTEGERS:
        return "integer"
    if node.kind in ("REAL", "DOUBLE"):
        return "number"
    if node.kind == "BOOLEAN":
        return "boolean"
    if node.kind == "ARRAY":
        return "array"
    if node.kind == "STRUCT":
        return "object"
    if node.kind == "MAP":
        return "array"
    return "string"


def shape(
    node: TypeNode, *, nullable: bool, null_elements: bool, null_fields: bool = True
) -> dict[str, Any]:
    """A JSON Schema subset for the values this type allows in a stored table.

    ``nullable`` is whether the value itself may be null; ``null_elements`` whether array elements
    (and map values) may be null (BigQuery stored arrays cannot hold NULL, Presto's can).
    """
    kind = _json_type(node)
    out: dict[str, Any] = {"type": [kind, "null"] if nullable else kind}
    if node.kind == "BYTES":
        out = {"type": ["object", "null"] if nullable else "object"}
    elif node.kind == "ARRAY" and node.element is not None:
        out["items"] = shape(node.element, nullable=null_elements, null_elements=null_elements)
    elif node.kind == "STRUCT":
        out["properties"] = {
            n: shape(t, nullable=null_fields and not not_null, null_elements=null_elements)
            for n, t, not_null in node.fields
        }
        out["required"] = [n for n, _, _ in node.fields]
        out["additionalProperties"] = False
    elif node.kind == "MAP" and node.key is not None and node.value is not None:
        out["items"] = {
            "type": "array",
            "prefixItems": [
                shape(node.key, nullable=False, null_elements=null_elements),
                shape(node.value, nullable=null_elements, null_elements=null_elements),
            ],
            "minItems": 2,
            "maxItems": 2,
        }
    return out


def leaf_value(node: TypeNode) -> Any:
    """A small valid non-null value of a scalar type."""
    if node.kind in INTEGERS:
        return 1
    if node.kind in ("REAL", "DOUBLE"):
        return 1.0
    if node.kind == "DECIMAL":
        return "1"
    if node.kind == "BOOLEAN":
        return False
    if node.kind == "DATE":
        return "2000-01-01"
    if node.kind == "TIMESTAMP":
        return "2000-01-01 00:00:00"
    if node.kind == "TIMESTAMPTZ":
        return "2000-01-01 00:00:00+00:00"
    if node.kind == "BYTES":
        return {"$bytes": ""}
    return "value"


def minimal_value(node: TypeNode, *, populate: bool, null_fields: bool = True) -> Any:
    """The smallest valid value: an empty array, a struct of minimal fields, a scalar.

    With ``populate`` an array holds one element, so that a mutation to empty is a change.
    """
    if node.kind == "ARRAY" and node.element is not None:
        if not populate:
            return []
        return [minimal_value(node.element, populate=populate, null_fields=null_fields)]
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        if not populate:
            return []
        return [
            [
                minimal_value(node.key, populate=populate),
                minimal_value(node.value, populate=populate, null_fields=null_fields),
            ]
        ]
    if node.kind == "STRUCT":
        return {
            n: (
                None
                if null_fields and not not_null and not populate
                else minimal_value(t, populate=populate, null_fields=null_fields)
            )
            for n, t, not_null in node.fields
        }
    return leaf_value(node)


def to_engine(node: TypeNode, value: Any) -> Any:
    """A state value as a python value an engine driver binds (dates, decimals, maps)."""
    if value is None:
        return None
    if node.kind == "ARRAY" and node.element is not None:
        return [to_engine(node.element, v) for v in value]
    if node.kind == "STRUCT":
        return {n: to_engine(t, value.get(n)) for n, t, _ in node.fields}
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        return {_hashable(to_engine(node.key, k)): to_engine(node.value, v) for k, v in value}
    if node.kind == "DECIMAL":
        return Decimal(str(value))
    if node.kind == "DATE":
        return date.fromisoformat(value)
    if node.kind in ("TIMESTAMP", "TIMESTAMPTZ"):
        return datetime.fromisoformat(value)
    if node.kind == "BYTES":
        return base64.b64decode(value["$bytes"])
    return value


def _hashable(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def duckdb_literal(node: TypeNode, value: Any) -> str:
    """A typed DuckDB literal for a state value (JSON form, or the python value of a scalar)."""
    typed = duckdb_type(node)
    if value is None:
        return f"CAST(NULL AS {typed})"
    if node.kind == "ARRAY" and node.element is not None:
        inner = ", ".join(duckdb_literal(node.element, v) for v in value)
        return f"CAST([{inner}] AS {typed})"
    if node.kind == "STRUCT":
        inner = ", ".join(f"'{n}': {duckdb_literal(t, value.get(n))}" for n, t, _ in node.fields)
        return f"CAST({{{inner}}} AS {typed})"
    if node.kind == "MAP" and node.key is not None and node.value is not None:
        keys = ", ".join(duckdb_literal(node.key, k) for k, _ in value)
        values = ", ".join(duckdb_literal(node.value, v) for _, v in value)
        return f"CAST(MAP([{keys}], [{values}]) AS {typed})"
    if node.kind == "BYTES":
        data = value if isinstance(value, bytes) else base64.b64decode(value["$bytes"])
        return f"from_base64('{base64.b64encode(data).decode('ascii')}')"
    if node.kind == "BOOLEAN":
        return "TRUE" if value else "FALSE"
    if node.kind in INTEGERS:
        return str(int(value))
    if node.kind in ("REAL", "DOUBLE"):
        return repr(float(value))
    text = str(value).replace("'", "''")
    return f"CAST('{text}' AS {typed})"
