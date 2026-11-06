"""SQL dialects: the language the queries are written in, separate from where states run.

A dialect says how to read queries and DDL (the SQLGlot name), which engines can run states for
it, and which engine to use when none is named. Engines are in `engines.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from isitright.packs.sql.errors import SqlInputError


@dataclass(frozen=True)
class Dialect:
    name: str
    read: str
    """The SQLGlot dialect that parses this dialect's queries and DDL."""
    family: str
    engines: tuple[str, ...]
    """Engines that can run generated states for this dialect; the first is the default."""
    warehouse: bool = False
    """Tables are usually qualified and rarely keyed; schema import is warehouse DDL."""

    @property
    def default_engine(self) -> str:
        return self.engines[0]


DIALECTS: dict[str, Dialect] = {
    d.name: d
    for d in (
        Dialect("sqlite", "sqlite", "sqlite", ("sqlite",)),
        Dialect("postgres", "postgres", "postgres", ("postgres", "duckdb")),
        Dialect("bigquery", "bigquery", "bigquery", ("duckdb",), warehouse=True),
        Dialect("presto", "presto", "presto", ("duckdb",), warehouse=True),
        Dialect("trino", "trino", "presto", ("duckdb",), warehouse=True),
    )
}

# `--engine` alone keeps its 0.6 meaning: the dialect that engine ran before 0.7.
_LEGACY_DIALECT = {"sqlite": "sqlite", "postgres": "postgres", "duckdb": "postgres"}


def get_dialect(name: str) -> Dialect:
    try:
        return DIALECTS[name]
    except KeyError:
        raise SqlInputError(f"dialect must be one of {', '.join(DIALECTS)}") from None


def resolve_dialect_and_engine(engine: str | None, dialect: str | None) -> tuple[Dialect, str]:
    """The dialect and the engine for the two (optional) names, or `SqlInputError`."""
    if dialect is None:
        chosen = get_dialect(_LEGACY_DIALECT.get(engine or "sqlite", engine or "sqlite"))
        return chosen, engine or chosen.default_engine
    chosen = get_dialect(dialect)
    if engine is None:
        return chosen, chosen.default_engine
    if engine not in chosen.engines:
        raise SqlInputError(
            f"dialect {chosen.name} cannot run on engine {engine}; "
            f"use {' or '.join(chosen.engines)}"
        )
    return chosen, engine
