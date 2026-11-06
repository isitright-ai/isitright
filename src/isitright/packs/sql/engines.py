"""The engine registry: where generated states run, and how faithfully.

An engine builds a host for a prepared schema. SQLite and PostgreSQL are native and isolated;
DuckDB is an emulation (a candidate generator) whose findings are confirmed on a native host.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from isitright.core.hosts import Fidelity
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.hosts import DuckdbHost, PostgresHost, SqlHost, SqliteHost
from isitright.packs.sql.postgres_ddl import Schema
from isitright.packs.sql.schema import DatabaseSchema


@dataclass(frozen=True)
class EngineSpec:
    name: str
    fidelity: Fidelity
    accepts_database_file: bool
    confirm_with: str | None
    """The native host that re-executes this engine's findings, if it is an emulation."""
    make_host: Callable[[DatabaseSchema, Schema | None, tuple[Any, str] | None], SqlHost]

    @property
    def emulated(self) -> bool:
        return self.fidelity is Fidelity.EMULATED


def _sqlite(db: DatabaseSchema, pg: Schema | None, server: tuple[Any, str] | None) -> SqlHost:
    return SqliteHost(db)


def _postgres(db: DatabaseSchema, pg: Schema | None, server: tuple[Any, str] | None) -> SqlHost:
    assert pg is not None
    return PostgresHost(pg, server)


def _duckdb(db: DatabaseSchema, pg: Schema | None, server: tuple[Any, str] | None) -> SqlHost:
    assert pg is not None
    return DuckdbHost(pg)


ENGINES: dict[str, EngineSpec] = {
    e.name: e
    for e in (
        EngineSpec("sqlite", Fidelity.NATIVE_ISOLATED, True, None, _sqlite),
        EngineSpec("postgres", Fidelity.NATIVE_ISOLATED, False, None, _postgres),
        EngineSpec("duckdb", Fidelity.EMULATED, False, "postgres", _duckdb),
    )
}


def get_engine(name: str) -> EngineSpec:
    try:
        return ENGINES[name]
    except KeyError:
        raise SqlInputError(f"engine must be one of {', '.join(ENGINES)}") from None


def open_host(spec: EngineSpec, host: SqlHost) -> AbstractContextManager[Any] | None:
    """Hosts that need a running server are context managers; others are used as built."""
    return host if isinstance(host, AbstractContextManager) else None
