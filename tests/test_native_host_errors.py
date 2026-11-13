"""A native host tells the query's own error apart from a failure to reach the engine.

Confirmation reads a query error of the candidate as "the candidate errors natively too", which
verifies a finding. A failure to reach the engine (a network error, an authentication, quota or
server error) must leave the finding unverified instead.

Proposed fixture: pending owner review (fake clients and queries written by Claude).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("duckdb")

from isitright.core.evidence import DivergenceStatus
from isitright.packs.sql import BigQueryHost, check
from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.native import ConnectionHost, NativeHostError, TrinoHost
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError

DDL = "CREATE TABLE t (id INT64, s STRING)"
SAFE = "SELECT id, SAFE_CAST(s AS INT64) AS n FROM t"
PLAIN = "SELECT id, CAST(s AS INT64) AS n FROM t"
INLINE = "SELECT 1 AS x"


class ServiceUnavailable(Exception):
    """Shaped like google.api_core's errors: an HTTP status in ``code``."""

    code = 503


class _Job:
    def __init__(self, failure: BaseException | None) -> None:
        self.failure = failure
        self.total_bytes_processed = 0
        self.total_bytes_billed = 0
        self.job_id = "job"
        self.schema = [
            type("F", (), {"name": n, "field_type": "INTEGER", "mode": "NULLABLE"})()
            for n in ("id", "n")
        ]

    def result(self, timeout: Any = None, max_results: Any = None) -> list[Any]:
        if self.failure is not None:
            raise self.failure
        return [(10, None)]


class _Client:
    """The reference runs; the candidate's result read fails with ``failure``."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    def query(self, sql: str, job_config: dict[str, Any], location: Any = None) -> _Job:
        if job_config.get("dry_run"):
            return _Job(None)
        return _Job(None if "SAFE_CAST" in sql else self.failure)


def _confirmed(failure: BaseException) -> Any:
    host = BigQueryHost(client_factory=lambda: _Client(failure), config_factory=lambda **kw: kw)
    return check(reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, confirm=host)


@pytest.mark.parametrize(
    "failure",
    [ConnectionError("connection reset"), TimeoutError("read timed out"), ServiceUnavailable()],
    ids=["connection", "timeout", "http-503"],
)
def test_a_failure_to_reach_bigquery_does_not_confirm_a_candidate_error(
    failure: BaseException,
) -> None:
    report = _confirmed(failure)
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "NOT_VERIFIED", verification
    assert report.findings[0].fidelity.verified_on is None


def test_a_query_error_on_bigquery_still_confirms_the_candidate_error() -> None:
    report = _confirmed(RuntimeError("Bad int64 value: x"))
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "VERIFIED"


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (ValueError("Division by zero"), QueryExecutionError),
        (RuntimeError("INVALID_CAST_ARGUMENT"), QueryExecutionError),
        (ConnectionRefusedError("refused"), NativeHostError),
        (OSError("network is unreachable"), NativeHostError),
    ],
)
def test_the_connection_host_classifies_what_the_users_function_raises(
    failure: BaseException, kind: type[Exception]
) -> None:
    def run(sql: str) -> tuple[list[str], list[list[Any]]]:
        raise failure

    host = ConnectionHost(run=run)
    with pytest.raises(kind) as raised:
        host.run_inline(INLINE, get_dialect("presto"), timeout_seconds=5, max_rows=10)
    assert type(raised.value) is kind  # a host error is not a query error, and the reverse
    assert str(failure) in str(raised.value)


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (RuntimeError("TrinoUserError(DIVISION_BY_ZERO)"), QueryExecutionError),
        (ConnectionError("connection refused"), NativeHostError),
    ],
)
def test_the_trino_host_classifies_errors_the_same_way(
    failure: BaseException, kind: type[Exception]
) -> None:
    class Cursor:
        description: list[Any] = []  # noqa: RUF012

        def execute(self, sql: str) -> None:
            raise failure

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    host = TrinoHost(connect=Connection)
    with pytest.raises(kind) as raised:
        host.run_inline(INLINE, get_dialect("trino"), timeout_seconds=5, max_rows=10)
    assert type(raised.value) is kind
