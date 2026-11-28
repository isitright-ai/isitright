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
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.native import ConnectionHost, NativeHostError, TrinoHost, engine_error
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


# --- setup failures, the status matrix, and the shapes the client libraries use -------------
#
# The libraries (google-cloud-bigquery, trino) are optional extras and are not installed in the
# test environment, so the exception shapes below imitate the documented ones: google.api_core's
# errors carry the HTTP status in ``code``; google.auth's credential errors carry none; the trino
# client raises ``Http<NNN>Error`` classes without a status attribute; requests' errors carry
# ``response.status_code`` and are OSErrors. Unverified against the real libraries: see REVIEW.md.


def _with_status(name: str, **attrs: Any) -> Exception:
    return type(name, (Exception,), attrs)(f"{name} happened")


@pytest.mark.parametrize("status", [401, 403, 407, 408, 429, 500, 502, 503, 504, 599])
def test_statuses_that_refuse_or_fail_the_caller_leave_the_finding_unconfirmed(
    status: int,
) -> None:
    for shape in (
        _with_status("GoogleShaped", code=status),
        _with_status("StatusCodeShaped", status_code=status),
        _with_status("HttpStatusShaped", http_status=status),
        _with_status("RequestsShaped", response=type("R", (), {"status_code": status})()),
        _with_status(f"Http{status}Error"),
    ):
        assert type(engine_error(shape)) is NativeHostError, (status, type(shape).__name__)


@pytest.mark.parametrize("status", [400, 404, 409, 412, 422, 499])
def test_statuses_about_the_query_stay_the_querys_own_error(status: int) -> None:
    for shape in (
        _with_status("GoogleShaped", code=status),
        _with_status("StatusCodeShaped", status_code=status),
        _with_status("RequestsShaped", response=type("R", (), {"status_code": status})()),
        _with_status(f"Http{status}Error"),
    ):
        assert type(engine_error(shape)) is QueryExecutionError, (status, type(shape).__name__)


@pytest.mark.parametrize("number", [1476, 8134, 0, 7, 9999, True])
def test_a_database_error_number_is_not_an_http_status(number: Any) -> None:
    # an Oracle ORA-01476 (division by zero) or SQL Server 8134 in ``code`` is the query's error
    assert type(engine_error(_with_status("OracleShaped", code=number))) is QueryExecutionError


def test_credential_failures_are_host_errors_whatever_their_class_carries() -> None:
    for name in ("DefaultCredentialsError", "RefreshError", "TransportError"):
        assert type(engine_error(_with_status(name))) is NativeHostError


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_bigquery_result_failures_by_status_do_not_confirm(status: int) -> None:
    verification = _confirmed(_with_status("GoogleShaped", code=status)).findings[0]
    assert verification.fidelity.verification.status == "NOT_VERIFIED"


@pytest.mark.parametrize("status", [400, 404])
def test_bigquery_result_failures_about_the_query_still_confirm(status: int) -> None:
    finding = _confirmed(_with_status("GoogleShaped", code=status)).findings[0]
    assert finding.fidelity.verification.status == "VERIFIED"


@pytest.mark.parametrize(
    "failure",
    [
        _with_status("DefaultCredentialsError"),
        ConnectionError("no route"),
        RuntimeError("client could not be built"),
        _with_status("GoogleShaped", code=400),  # even a query-shaped error: this is not a query
    ],
    ids=["credentials", "network", "generic", "query-shaped"],
)
def test_a_failure_to_build_the_bigquery_client_is_a_host_error(failure: BaseException) -> None:
    def factory() -> Any:
        raise failure

    host = BigQueryHost(client_factory=factory, config_factory=lambda **kw: kw)
    with pytest.raises(NativeHostError, match="cannot reach the engine"):
        host.run_inline(INLINE, get_dialect("bigquery"), timeout_seconds=5, max_rows=10)
    report = check(
        reference_sql=SAFE, candidate_sql=PLAIN, dialect="bigquery", ddl=DDL, confirm=host
    )
    verification = report.findings[0].fidelity.verification
    assert verification is not None and verification.status == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionRefusedError("refused"),
        ValueError("bad connect arguments"),
        _with_status("Http503Error"),
        _with_status("GoogleShaped", code=400),
    ],
    ids=["refused", "value-error", "http-503", "query-shaped"],
)
def test_a_failure_to_open_the_trino_connection_is_a_host_error(failure: BaseException) -> None:
    def connect() -> Any:
        raise failure

    host = TrinoHost(connect=connect)
    with pytest.raises(NativeHostError, match="cannot reach the engine") as raised:
        host.run_inline(INLINE, get_dialect("trino"), timeout_seconds=5, max_rows=10)
    assert type(raised.value) is NativeHostError


def test_a_missing_client_library_is_still_an_input_error_not_a_host_error() -> None:
    def factory() -> Any:
        raise SqlInputError("install isitright[bigquery]")

    host = BigQueryHost(client_factory=factory, config_factory=lambda **kw: kw)
    with pytest.raises(SqlInputError, match="install isitright"):
        host.run_inline(INLINE, get_dialect("bigquery"), timeout_seconds=5, max_rows=10)

    def connect() -> Any:
        raise SqlInputError("install isitright[trino]")

    with pytest.raises(SqlInputError):
        TrinoHost(connect=connect).run_inline(
            INLINE, get_dialect("trino"), timeout_seconds=5, max_rows=10
        )


# --- the real exception classes, when the client libraries are installed -------------------------
# (the extras ``bigquery`` and ``trino`` are not in CI's ``all``, so these run only where the
# libraries are present; the shapes above are the same ones, written by hand)


def test_trino_client_classes_are_told_apart() -> None:
    exceptions = pytest.importorskip("trino.exceptions")
    for name in ("TrinoConnectionError", "TrinoAuthError", "HttpError"):
        assert type(engine_error(getattr(exceptions, name)("x"))) is NativeHostError, name
    for name in ("Http502Error", "Http503Error", "Http504Error"):
        assert type(engine_error(getattr(exceptions, name)("x"))) is NativeHostError, name
    query = {"errorName": "DIVISION_BY_ZERO", "message": "Division by zero", "errorCode": 8}
    assert type(engine_error(exceptions.TrinoUserError(query))) is QueryExecutionError


def test_google_client_classes_are_told_apart() -> None:
    api = pytest.importorskip("google.api_core.exceptions")
    for name in (
        "Forbidden",
        "Unauthorized",
        "TooManyRequests",
        "ServiceUnavailable",
        "InternalServerError",
        "DeadlineExceeded",
    ):
        assert type(engine_error(getattr(api, name)("x"))) is NativeHostError, name
    for name in ("BadRequest", "NotFound"):
        assert type(engine_error(getattr(api, name)("x"))) is QueryExecutionError, name
    auth = pytest.importorskip("google.auth.exceptions")
    for name in ("DefaultCredentialsError", "RefreshError", "TransportError"):
        assert type(engine_error(getattr(auth, name)("x"))) is NativeHostError, name


def test_requests_errors_are_host_errors() -> None:
    requests = pytest.importorskip("requests")
    for error in (
        requests.exceptions.ConnectionError("x"),
        requests.exceptions.Timeout("x"),
        requests.exceptions.HTTPError("x"),
    ):
        assert type(engine_error(error)) is NativeHostError
