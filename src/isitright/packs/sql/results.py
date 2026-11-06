"""Nested query-result values, canonicalized per dialect.

A struct is a mapping, an array a list, a map a list of ``[key, value]`` pairs sorted by key
(a map has no order). BigQuery raises an error when a result holds an array with a NULL element, and
reports a NULL array as an empty one (documented, decision E2 and E4); both are applied where the
dialect says so, so a world that hits either is a per-world query error, not a finding.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.models import CanonicalValue, CanonicalValueKind
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError


def nested_value(value: Any, dialect: Dialect | None) -> CanonicalValue:
    """A list or mapping from an engine as a canonical JSON value."""
    return CanonicalValue(
        kind=CanonicalValueKind.JSON, value=_json(value, dialect), engine_type="NESTED"
    )


def empty_array(dialect: Dialect | None) -> CanonicalValue:
    """BigQuery reports a NULL array in a query result as an empty array."""
    return nested_value([], dialect)


def _json(value: Any, dialect: Dialect | None) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list | tuple):
        items = [_json(v, dialect) for v in value]
        if dialect is not None and not dialect.null_elements and any(i is None for i in items):
            raise QueryExecutionError(
                f"{dialect.name} raises an error when a query result has an array with NULL "
                "elements"
            )
        return items
    if isinstance(value, dict):
        return {str(k): _json(v, dialect) for k, v in value.items()}
    raise QueryExecutionError(f"unsupported nested result type: {type(value).__name__}")
