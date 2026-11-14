"""Native confirmation hosts for warehouses: `NATIVE_INLINE`.

A host runs query text in which every table is an inline literal table (see `inline.py`). Before
anything is sent, the text is parsed again and refused if it still names a table
(`RealTableReference`).
BigQuery adds a dry run, a cap on billed bytes and job labels. The user's own engine is reached by
a function they supply. The search never runs here: only the states of a divergence are confirmed.

Credentials are read by the client library from the environment at the moment the client is built.
Nothing here reads, stores, prints or reports a credential, a key file path or a token.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isitright import __version__
from isitright.core.hosts import Fidelity
from isitright.packs.sql.dialects import Dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.inline import assert_inline_only
from isitright.packs.sql.models import QueryResult
from isitright.packs.sql.postgres_server import _result
from isitright.packs.sql.sqlite_sandbox import QueryExecutionError

BIGQUERY_MAX_SQL_CHARS = 900_000
"""BigQuery's limit on the length of a standard SQL query is 1 MB of text (to be confirmed by the
runbook); the host refuses over 900,000 characters rather than send a query it will reject."""
DEFAULT_MAX_BYTES_BILLED = 100 * 1024 * 1024
DEFAULT_DRY_RUN_BOUND = 10 * 1024 * 1024
"""Inline data scans nothing. A dry run above this bound means a table is being read: refuse."""


class NativeHostError(RuntimeError):
    """The native host could not run a query (not a result: the finding stays unconfirmed)."""


UNREACHABLE_STATUS = frozenset({401, 403, 407, 408, 429})
"""HTTP statuses that say the engine was not reached or refused the caller, not the query."""


_CREDENTIAL_ERRORS = frozenset(
    {"DefaultCredentialsError", "RefreshError", "TransportError", "Unauthenticated"}
)
"""google.auth's failures to obtain or refresh credentials: they carry no HTTP status."""


def _http_status(error: BaseException) -> int | None:
    """The HTTP status an exception carries, by the shapes the client libraries use: ``code``
    (google.api_core), ``status_code``, ``http_status``, ``response.status_code`` (requests), or a
    class named ``Http<NNN>Error`` (the trino client). Only 100 to 599 counts: a ``code`` of a
    database's own error number (Oracle's 1476, SQL Server's 8134) is not an HTTP status."""
    for name in ("code", "status_code", "http_status"):
        value = getattr(error, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    match = re.fullmatch(r"Http(\d{3})Error", type(error).__name__)
    return int(match.group(1)) if match else None


def engine_error(error: BaseException) -> Exception:
    """What an exception raised while a native engine ran a query means.

    A failure to reach the engine (an ``OSError``: a network error, a refused connection, a timeout
    of the transport; or a credentials failure) or an HTTP status that refuses the caller
    (authentication, quota) or reports a server error (5xx) is a ``NativeHostError``: the finding
    stays unconfirmed. Anything else is the query's own error (``QueryExecutionError``), which
    confirmation may read as "the candidate errors natively too". Before 0.9 every exception was a
    query error, so a dropped connection on the candidate's run confirmed a candidate-errors
    finding.
    """
    status = _http_status(error)
    if (
        isinstance(error, OSError)
        or type(error).__name__ in _CREDENTIAL_ERRORS
        or (status is not None and (status >= 500 or status in UNREACHABLE_STATUS))
    ):
        return NativeHostError(f"{type(error).__name__}: {error}")
    return QueryExecutionError(f"{type(error).__name__}: {error}")


def connect_error(error: BaseException) -> NativeHostError:
    """A failure to build the client or connection: never a query's error."""
    return NativeHostError(f"cannot reach the engine: {type(error).__name__}: {error}")


@dataclass
class _Cursor:
    """Just enough of a DB-API cursor for the shared result canonicalizer."""

    names: list[str]
    types: list[str]
    rows: list[tuple[Any, ...]]

    @property
    def description(self) -> list[tuple[str, str]]:
        return list(zip(self.names, self.types, strict=True))

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        return self.rows[:size]


@dataclass
class InlineHost:
    """Common surface: a guard in front of an engine-specific `_execute`."""

    dialect_name: str = ""
    fidelity: Fidelity = Fidelity.NATIVE_INLINE
    engine: str = ""
    version: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    """What was run: phase, bytes, job id. Never credentials."""

    def run_inline(
        self, sql: str, dialect: Dialect, *, timeout_seconds: float, max_rows: int
    ) -> QueryResult:
        assert_inline_only(sql, dialect)
        return self._execute(sql, dialect, timeout_seconds, max_rows)

    def _execute(self, sql: str, dialect: Dialect, timeout: float, max_rows: int) -> QueryResult:
        raise NotImplementedError


def load_env_file(path: Path, names: list[str]) -> None:
    """Set only the named variables from a dotenv-style file, unless the environment has them.

    Nothing else in the file is read into the environment and no value is printed or returned.
    """
    wanted = set(names)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        if name in wanted and name not in os.environ:
            os.environ[name] = value.strip().strip("'\"")


# --- BigQuery -------------------------------------------------------------------------------------


def _default_client(project: str | None) -> Any:
    try:
        bigquery = importlib.import_module("google.cloud.bigquery")
    except ImportError as error:
        raise SqlInputError(
            "BigQuery confirmation needs the client library: install isitright[bigquery]"
        ) from error
    return bigquery.Client(project=project)


def _default_config(**kwargs: Any) -> Any:
    bigquery = importlib.import_module("google.cloud.bigquery")
    return bigquery.QueryJobConfig(**kwargs)


@dataclass
class BigQueryHost(InlineHost):
    """BigQuery with the state inlined: refusal check, dry run, a cap on bytes billed, labels."""

    client_factory: Callable[[], Any] | None = None
    config_factory: Callable[..., Any] = _default_config
    project: str | None = None
    max_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED
    dry_run_bound: int = DEFAULT_DRY_RUN_BOUND
    labels: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    engine: str = "bigquery"
    _client: Any = None

    def __post_init__(self) -> None:
        self.dialect_name = "bigquery"
        self.labels = {
            "isitright": "1",
            "isitright_version": __version__.replace(".", "_").lower(),
            "isitright_phase": "confirm",
            **self.labels,
        }

    def _client_now(self) -> Any:
        if self._client is None:
            factory = self.client_factory or (lambda: _default_client(self.project))
            self._client = factory()
        return self._client

    def _execute(self, sql: str, dialect: Dialect, timeout: float, max_rows: int) -> QueryResult:
        if len(sql) > BIGQUERY_MAX_SQL_CHARS:
            raise NativeHostError(
                f"the query is {len(sql)} characters; BigQuery's limit is about 1 MB of text"
            )
        try:
            client = self._client_now()
        except SqlInputError:
            raise  # the client library is not installed: the caller must be told so
        except Exception as error:
            raise connect_error(error) from error
        options: dict[str, Any] = {"use_query_cache": False, "labels": dict(self.labels)}
        try:
            dry = client.query(
                sql,
                job_config=self.config_factory(dry_run=True, **options),
                location=self.location,
            )
            estimate = int(getattr(dry, "total_bytes_processed", 0) or 0)
            self.records.append({"phase": "dry_run", "estimated_bytes": estimate})
            if estimate > self.dry_run_bound:
                raise NativeHostError(
                    f"the dry run estimates {estimate} bytes for a query that should read none: "
                    "a table may still be referenced; not sent"
                )
            job = client.query(
                sql,
                job_config=self.config_factory(
                    maximum_bytes_billed=self.max_bytes_billed, **options
                ),
                location=self.location,
            )
        except NativeHostError:
            raise
        except Exception as error:
            raise NativeHostError(f"{type(error).__name__}: {error}") from error
        try:
            rows = list(job.result(timeout=timeout, max_results=max_rows + 1))
            schema = list(getattr(job, "schema", None) or getattr(job.result(), "schema", []))
        except Exception as error:
            raise engine_error(error) from error
        self.records.append(
            {
                "phase": "run",
                "bytes_billed": getattr(job, "total_bytes_billed", None),
                "job_id": getattr(job, "job_id", None),
            }
        )
        names = [getattr(f, "name", f"f{i}") for i, f in enumerate(schema)]
        types = [
            "ARRAY[]" if getattr(f, "mode", "") == "REPEATED" else str(getattr(f, "field_type", ""))
            for f in schema
        ]
        data = [tuple(row.values()) if hasattr(row, "values") else tuple(row) for row in rows]
        return _result(_Cursor(names, types, data), max_rows, dialect=dialect)


# --- Trino and the user's own engine ------------------------------------------------------------


@dataclass
class TrinoHost(InlineHost):
    """A Trino server reached with the `trino` client (a local one for tests, or the user's)."""

    connect: Callable[[], Any] | None = None
    host: str = "localhost"
    port: int = 8080
    user: str = "isitright"
    catalog: str = "memory"
    schema: str = "default"
    engine: str = "trino"

    def __post_init__(self) -> None:
        self.dialect_name = "trino"

    def _connection(self) -> Any:
        if self.connect is not None:
            return self.connect()
        try:
            dbapi = importlib.import_module("trino.dbapi")
        except ImportError as error:
            raise SqlInputError(
                "Trino confirmation needs the client library: install isitright[trino]"
            ) from error
        return dbapi.connect(
            host=self.host, port=self.port, user=self.user, catalog=self.catalog, schema=self.schema
        )

    def _execute(self, sql: str, dialect: Dialect, timeout: float, max_rows: int) -> QueryResult:
        try:
            connection = self._connection()
        except SqlInputError:
            raise
        except Exception as error:
            raise connect_error(error) from error
        try:
            cursor = connection.cursor()
            cursor.execute(sql)
            rows = cursor.fetchmany(max_rows + 1)
            description = cursor.description or []
        except Exception as error:
            raise engine_error(error) from error
        finally:
            close = getattr(connection, "close", None)
            if close is not None:
                close()
        names = [str(d[0]) for d in description]
        types = [str(d[1]) for d in description]
        self.records.append({"phase": "run", "rows": len(rows)})
        return _result(_Cursor(names, types, [tuple(r) for r in rows]), max_rows, dialect=dialect)


@dataclass
class ConnectionHost(InlineHost):
    """The user's engine, reached by a function ``run(sql) -> (columns, rows)`` they supply.

    isitright sends only inline text (the refusal check runs first) and one query per call. The
    function is trusted code and owns its own timeouts; here a call that runs past the timeout is
    abandoned (its thread keeps running until it returns).
    """

    run: Callable[[str], tuple[list[str], list[list[Any]]]] | None = None
    engine: str = "connection"

    def __post_init__(self) -> None:
        self.dialect_name = "connection"

    def _execute(self, sql: str, dialect: Dialect, timeout: float, max_rows: int) -> QueryResult:
        assert self.run is not None
        outcome: list[Any] = []

        def call() -> None:
            try:
                outcome.append(self.run(sql))  # type: ignore[misc]
            except BaseException as error:
                outcome.append(error)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout)
        if not outcome:
            raise NativeHostError(f"the connection function did not return within {timeout} s")
        if isinstance(outcome[0], BaseException):
            raise engine_error(outcome[0])
        columns, rows = outcome[0]
        self.records.append({"phase": "run", "rows": len(rows)})
        return _result(
            _Cursor(list(columns), [""] * len(columns), [tuple(r) for r in rows]),
            max_rows,
            dialect=dialect,
        )


def load_connection(spec: str) -> Callable[[str], tuple[list[str], list[list[Any]]]]:
    """``module:function`` as a callable. The caller must have been given ``--trust-code``."""
    module_name, separator, function = spec.partition(":")
    if not separator or not module_name or not function:
        raise SqlInputError("--connection must look like module:function")
    try:
        func = getattr(importlib.import_module(module_name), function)
    except (ImportError, AttributeError) as error:
        raise SqlInputError(f"cannot load connection {spec!r}: {error}") from error
    if not callable(func):
        raise SqlInputError(f"{spec!r} is not callable")
    return func  # type: ignore[no-any-return]
