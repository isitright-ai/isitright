"""Conservative generated values for a small shared SQL type subset."""

from __future__ import annotations

from decimal import Decimal

from isitright.packs.sql.schema import ColumnSchema
from isitright.packs.sql.state import SqlValue

INTEGER_TYPES = frozenset({"INT", "INTEGER", "SMALLINT", "BIGINT"})
FLOAT_TYPES = frozenset({"REAL", "DOUBLE"})
KEY_TYPES = INTEGER_TYPES | {"TEXT", "UUID"}
SYNTHETIC_TYPES = (
    KEY_TYPES | FLOAT_TYPES | {"DECIMAL", "BOOLEAN", "DATE", "TIMESTAMP", "TIMESTAMPTZ"}
)


def generated_value(column: ColumnSchema, ordinal: int, *, foreign_key: bool = False) -> SqlValue:
    """Return deterministic non-null values for required fields and related keys."""
    kind = column.declared_type.upper()
    key_ordinal = 1 if foreign_key else ordinal
    if column.primary_key_position or foreign_key:
        if kind in INTEGER_TYPES:
            return key_ordinal
        if kind == "TEXT":
            text_key = f"key-{key_ordinal}"
            if column.type_parameters and len(text_key) > column.type_parameters[0]:
                return str(key_ordinal)[-column.type_parameters[0] :]
            return text_key
        if kind == "UUID":
            return f"00000000-0000-0000-0000-{key_ordinal:012d}"
        raise ValueError(f"unsupported key type: {kind}")
    if kind in INTEGER_TYPES:
        return 10
    if kind == "DECIMAL":
        return Decimal("0") if column.type_parameters else Decimal("10")
    if kind in FLOAT_TYPES:
        return 10.0
    if kind == "BOOLEAN":
        return False
    if kind == "DATE":
        return "2000-01-01"
    if kind in {"TIMESTAMP", "TIMESTAMPTZ"}:
        return "2000-01-01 00:00:00" + ("+00" if kind == "TIMESTAMPTZ" else "")
    if kind == "UUID":
        return "00000000-0000-0000-0000-000000000001"
    if kind == "TEXT":
        if not column.not_null:
            return None
        return "value"[: column.type_parameters[0]] if column.type_parameters else "value"
    raise ValueError(f"unsupported generated type: {kind}")
