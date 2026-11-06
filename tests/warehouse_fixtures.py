# Proposed fixture: pending owner review.
# Written by Claude, who also wrote the translation under test. The native outcomes are the
# behavior the engines' documentation states (claim ids E1..E17 in the 0.7 DECISIONS notes); a
# documented outcome is not a confirmed one. Every native outcome below is `confirmed=False` until
# the owner's BigQuery runbook (smoke test) or a local Trino has run it.
"""Dialect fidelity fixtures for the DuckDB emulation of BigQuery and Presto/Trino.

Each fixture is one query on a small fixed state with the outcome it has on the emulation after
translation, the outcome the engine documents, and a status:

* ``agrees``: the emulation and the documented native outcome are the same, without any rewrite
  beyond what SQLGlot does on its own;
* ``translated``: a plain SQLGlot transpile would differ from the documented outcome (or lose the
  construct), and the pack rewrites it so that the two agree;
* ``checked``: DuckDB itself differs, and the rule is applied when results are read (a NULL array
  in a BigQuery result is empty; an array with a NULL element in a BigQuery result is an error);
* ``detected``: the pack refuses the query, naming the construct;
* ``listed``: a known divergence that is neither translated nor detected (documented in
  ``docs/sql/supported-sql.md``).

``ERROR`` stands for a query error. ``None`` for ``native`` means the documentation page that was
read does not state the outcome; the fixture then pins only the emulated outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR = "ERROR"


@dataclass(frozen=True)
class Fixture:
    id: str
    dialect: str
    query: str
    emulated: Any
    native: Any
    status: str
    source: str
    """The documented claim the native outcome rests on (DECISIONS section E), or why none."""
    ordered: bool = False
    rows_note: str = ""
    confirmed: bool = False
    detected_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


BQ_DDL = (
    "CREATE TABLE d.t (id INT64, x INT64, f FLOAT64, d DATE, ts TIMESTAMP, "
    "arr ARRAY<INT64>, s STRING)"
)
BQ_ROWS = {
    "t": [
        {
            "id": 1,
            "x": None,
            "f": 1.5,
            "d": "2021-01-06",
            "ts": "2021-01-06 23:30:00+00:00",
            "arr": [1, 2],
            "s": "a",
        },
        {
            "id": 2,
            "x": 5,
            "f": 2.5,
            "d": "2021-01-10",
            "ts": "2021-01-10 00:30:00+00:00",
            "arr": [],
            "s": "b",
        },
        {"id": 3, "x": 9, "f": 0.0, "d": "2021-01-11", "ts": None, "arr": [], "s": None},
    ]
}

PRESTO_DDL = (
    "CREATE TABLE web.t (id bigint, x bigint, f double, d date, arr array(bigint), "
    "m map(varchar, bigint), s varchar)"
)
PRESTO_ROWS = {
    "t": [
        {
            "id": 1,
            "x": None,
            "f": 1.5,
            "d": "2021-01-06",
            "arr": [1, 2],
            "m": [["a", 1]],
            "s": "a",
        },
        {"id": 2, "x": 5, "f": 2.5, "d": "2021-01-10", "arr": [], "m": [], "s": "b"},
        {"id": 3, "x": 9, "f": 0.0, "d": "2021-01-11", "arr": None, "m": None, "s": None},
    ]
}

BIGQUERY: tuple[Fixture, ...] = (
    Fixture(
        "bq-null-order-asc",
        "bigquery",
        "SELECT x FROM t ORDER BY x",
        [[None], [5], [9]],
        [[None], [5], [9]],
        "agrees",
        "E11 (NULLS FIRST by default when ascending)",
        ordered=True,
    ),
    Fixture(
        "bq-null-order-desc",
        "bigquery",
        "SELECT x FROM t ORDER BY x DESC",
        [[9], [5], [None]],
        [[9], [5], [None]],
        "agrees",
        "E11 (NULLS LAST by default when descending)",
        ordered=True,
    ),
    Fixture(
        "bq-unnest-cross-empty-array",
        "bigquery",
        "SELECT t.id, e FROM t CROSS JOIN UNNEST(t.arr) AS e",
        [[1, 1], [1, 2]],
        [[1, 1], [1, 2]],
        "agrees",
        "E9 (empty arrays produce zero rows)",
    ),
    Fixture(
        "bq-unnest-left-empty-array",
        "bigquery",
        "SELECT t.id, e FROM t LEFT JOIN UNNEST(t.arr) AS e",
        [[1, 1], [1, 2], [2, None], [3, None]],
        [[1, 1], [1, 2], [2, None], [3, None]],
        "agrees",
        "E9 (zero rows from UNNEST) with LEFT JOIN keeping the row; the page does not spell out "
        "the LEFT JOIN case, so it is part of what the runbook confirms",
    ),
    Fixture(
        "bq-unnest-with-offset",
        "bigquery",
        "SELECT t.id, e, o FROM t, UNNEST(t.arr) AS e WITH OFFSET AS o",
        [[1, 1, 0], [1, 2, 1]],
        [[1, 1, 0], [1, 2, 1]],
        "translated",
        "E10 (offset counting starts at zero); DuckDB's ordinality starts at one and SQLGlot "
        "gives no warning",
    ),
    Fixture(
        "bq-unnest-with-offset-no-element-alias",
        "bigquery",
        "SELECT t.id, o FROM t, UNNEST(t.arr) WITH OFFSET AS o",
        [[1, 0], [1, 1]],
        [[1, 0], [1, 1]],
        "translated",
        "E10; SQLGlot drops the offset's name when the element has no alias",
    ),
    Fixture(
        "bq-array-offset-out-of-range",
        "bigquery",
        "SELECT arr[OFFSET(5)] FROM t WHERE id = 1",
        ERROR,
        ERROR,
        "translated",
        "E5 (OFFSET produces an error if the index is out of range); DuckDB gives NULL",
    ),
    Fixture(
        "bq-array-offset-in-range",
        "bigquery",
        "SELECT arr[OFFSET(0)], arr[ORDINAL(2)] FROM t WHERE id = 1",
        [[1, 2]],
        [[1, 2]],
        "agrees",
        "E5 (zero-based OFFSET); ORDINAL is one-based",
    ),
    Fixture(
        "bq-array-safe-offset-out-of-range",
        "bigquery",
        "SELECT arr[SAFE_OFFSET(5)], arr[SAFE_OFFSET(-2)] FROM t WHERE id = 1",
        [[None, None]],
        [[None, None]],
        "translated",
        "E6 (SAFE_OFFSET returns NULL if the index is out of range); a negative index counts "
        "from the end in DuckDB",
    ),
    Fixture(
        "bq-division-by-zero",
        "bigquery",
        "SELECT id / 0 FROM t",
        ERROR,
        ERROR,
        "translated",
        "E7 (divide by zero operations return an error); DuckDB returns infinity",
    ),
    Fixture(
        "bq-division-by-zero-column",
        "bigquery",
        "SELECT x / (x - x) FROM t WHERE id = 2",
        ERROR,
        ERROR,
        "translated",
        "E7",
    ),
    Fixture(
        "bq-integer-division-is-float",
        "bigquery",
        "SELECT id / 2 FROM t WHERE id = 1",
        [[0.5]],
        None,
        "agrees",
        "not fetched: the operators page read does not quote the INT64 / INT64 result type",
    ),
    Fixture(
        "bq-safe-divide",
        "bigquery",
        "SELECT SAFE_DIVIDE(f, f) FROM t",
        [[1.0], [1.0], [None]],
        None,
        "agrees",
        "not fetched: SAFE_DIVIDE is not quoted from the page read",
    ),
    Fixture(
        "bq-integer-overflow",
        "bigquery",
        "SELECT id + 9223372036854775807 FROM t",
        ERROR,
        ERROR,
        "agrees",
        "E8 (all operators throw an error if the computation result overflows)",
    ),
    Fixture(
        "bq-dayofweek",
        "bigquery",
        "SELECT EXTRACT(DAYOFWEEK FROM d) FROM t WHERE id = 1",
        [[4]],
        [[4]],
        "translated",
        "E13 (range [1,7] with Sunday as the first day); 2021-01-06 is a Wednesday. DuckDB "
        "counts from 0",
    ),
    Fixture(
        "bq-date-trunc-week",
        "bigquery",
        "SELECT DATE_TRUNC(d, WEEK) FROM t WHERE id IN (1, 3)",
        [["2021-01-03"], ["2021-01-10"]],
        [["2021-01-03"], ["2021-01-10"]],
        "translated",
        "E12 (weeks begin on Sundays); DuckDB's week begins on Monday and returns a timestamp",
    ),
    Fixture(
        "bq-date-trunc-month-is-a-date",
        "bigquery",
        "SELECT DATE_TRUNC(d, MONTH) FROM t WHERE id = 1",
        [["2021-01-01"]],
        None,
        "translated",
        "not fetched: BigQuery returns a DATE; DuckDB returns a timestamp",
    ),
    Fixture(
        "bq-timestamp-is-utc",
        "bigquery",
        "SELECT EXTRACT(HOUR FROM ts), DATE(ts) FROM t WHERE id = 1",
        [[23, "2021-01-06"]],
        None,
        "translated",
        "not fetched: BigQuery reads a TIMESTAMP in UTC; DuckDB uses the machine's zone unless "
        "the session is set to UTC (it is)",
    ),
    Fixture(
        "bq-array-agg-ignore-nulls",
        "bigquery",
        "SELECT ARRAY_AGG(e IGNORE NULLS ORDER BY e) FROM t, UNNEST(arr) AS e",
        [[[1, 2]]],
        None,
        "translated",
        "not fetched: IGNORE NULLS is dropped by SQLGlot and a NULLS FIRST is added; rewritten "
        "as FILTER (WHERE e IS NOT NULL)",
    ),
    Fixture(
        "bq-array-agg-null-element-in-result",
        "bigquery",
        "SELECT ARRAY_AGG(x) FROM t",
        ERROR,
        ERROR,
        "checked",
        "E4 (an error if the query result has an array which contains NULL elements)",
    ),
    Fixture(
        "bq-null-array-in-result-is-empty",
        "bigquery",
        "SELECT CAST(NULL AS ARRAY<INT64>)",
        [[[]]],
        [[[]]],
        "checked",
        "E2 (a NULL array is an empty array in the query result)",
    ),
    Fixture(
        "bq-null-and-empty-arrays-differ-inside-a-query",
        "bigquery",
        "SELECT ARRAY_LENGTH(CAST(NULL AS ARRAY<INT64>)) IS NULL, ARRAY_LENGTH([]) = 0",
        [[True, True]],
        [[True, True]],
        "agrees",
        "E3 (inside the query, NULL and empty arrays are two distinct values)",
    ),
    Fixture(
        "bq-cast-rounds-half-away",
        "bigquery",
        "SELECT CAST(2.5 AS INT64), CAST(-2.5 AS INT64)",
        [[3, -3]],
        None,
        "agrees",
        "not fetched: rounding of CAST(FLOAT64 AS INT64)",
    ),
    Fixture(
        "bq-array-agg-limit",
        "bigquery",
        "SELECT ARRAY_AGG(id ORDER BY id LIMIT 2) FROM t",
        "REJECTED",
        None,
        "detected",
        "no exact DuckDB form for LIMIT inside ARRAY_AGG",
        detected_text="LIMIT inside ARRAY_AGG",
    ),
    Fixture(
        "bq-wildcard-table",
        "bigquery",
        "SELECT * FROM `p.d.t_*`",
        "REJECTED",
        None,
        "detected",
        "wildcard tables are rewritten in the benchmark copy only (not in the pack)",
        detected_text="wildcard table",
    ),
    Fixture(
        "bq-geography",
        "bigquery",
        "SELECT ST_GEOGPOINT(1, 2) FROM t",
        "REJECTED",
        None,
        "detected",
        "geography is not supported in 0.7",
        detected_text="geography",
    ),
)

PRESTO: tuple[Fixture, ...] = (
    Fixture(
        "pr-integer-division",
        "presto",
        "SELECT 5 / 2",
        [[2]],
        [[2]],
        "translated",
        "E16 (integer division performs truncation); DuckDB's / is floating point",
    ),
    Fixture(
        "pr-integer-division-column",
        "presto",
        "SELECT id / x FROM t",
        [[None], [0], [0]],
        None,
        "translated",
        "E16",
    ),
    Fixture(
        "pr-division-by-zero",
        "presto",
        "SELECT id / 0 FROM t",
        ERROR,
        None,
        "translated",
        "E16 does not state division by zero; Presto and Trino raise an error (unconfirmed "
        "recollection)",
    ),
    Fixture(
        "pr-array-subscript-out-of-bounds",
        "presto",
        "SELECT arr[5] FROM t WHERE id = 1",
        ERROR,
        ERROR,
        "translated",
        "E14 (the subscript fails where element_at returns NULL); DuckDB gives NULL",
    ),
    Fixture(
        "pr-array-subscript-in-bounds",
        "presto",
        "SELECT arr[1], arr[2] FROM t WHERE id = 1",
        [[1, 2]],
        [[1, 2]],
        "agrees",
        "E14 (indexed starting from one)",
    ),
    Fixture(
        "pr-element-at-out-of-bounds",
        "presto",
        "SELECT element_at(arr, 5) FROM t WHERE id = 1",
        [[None]],
        [[None]],
        "agrees",
        "E14 (element_at returns NULL when accessing an index larger than array length)",
    ),
    Fixture(
        "pr-map-subscript-missing-key",
        "presto",
        "SELECT m['zz'] FROM t WHERE id = 1",
        ERROR,
        ERROR,
        "translated",
        "E15 (the operator throws an error if the key is not contained in the map)",
    ),
    Fixture(
        "pr-map-element-at-missing-key",
        "presto",
        "SELECT element_at(m, 'zz') FROM t WHERE id = 1",
        [[None]],
        [[None]],
        "agrees",
        "E15 (element_at returns NULL)",
    ),
    Fixture(
        "pr-unnest-cross-null-and-empty",
        "presto",
        "SELECT t.id, e FROM t CROSS JOIN UNNEST(t.arr) AS u(e)",
        [[1, 1], [1, 2]],
        [[1, 1], [1, 2]],
        "agrees",
        "E17 (UNNEST returns zero entries when the array is empty, or null)",
    ),
    Fixture(
        "pr-unnest-left-join-keeps-row",
        "presto",
        "SELECT t.id, e FROM t LEFT JOIN UNNEST(t.arr) AS u(e) ON TRUE",
        [[1, 1], [1, 2], [2, None], [3, None]],
        [[1, 1], [1, 2], [2, None], [3, None]],
        "agrees",
        "E17 (LEFT JOIN is preferable to avoid losing the row)",
    ),
    Fixture(
        "pr-null-order-asc",
        "presto",
        "SELECT x FROM t ORDER BY x",
        [[5], [9], [None]],
        [[5], [9], [None]],
        "agrees",
        "E17 (the default null ordering is NULLS LAST, regardless of direction)",
        ordered=True,
    ),
    Fixture(
        "pr-null-order-desc",
        "presto",
        "SELECT x FROM t ORDER BY x DESC",
        [[9], [5], [None]],
        [[9], [5], [None]],
        "agrees",
        "E17",
        ordered=True,
    ),
    Fixture(
        "pr-date-trunc-week-is-a-date",
        "presto",
        "SELECT date_trunc('week', d) FROM t WHERE id = 1",
        [["2021-01-04"]],
        None,
        "translated",
        "not fetched: a Presto week begins on Monday and the result keeps the DATE type; "
        "DuckDB returns a timestamp",
    ),
    Fixture(
        "pr-null-elements-in-result-arrays",
        "presto",
        "SELECT ARRAY[1, NULL]",
        [[[1, None]]],
        None,
        "agrees",
        "not fetched: Presto allows NULL elements in arrays (BigQuery does not in results)",
    ),
    Fixture(
        "pr-cast-varchar-to-integer-fails",
        "presto",
        "SELECT CAST('abc' AS INTEGER)",
        ERROR,
        None,
        "agrees",
        "not fetched: invalid casts fail in both",
    ),
)

FIXTURES: tuple[Fixture, ...] = BIGQUERY + PRESTO
