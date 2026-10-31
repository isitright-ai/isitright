"""A third-party MCP server as the host's service: seeded from a world, read back after a run.

The simulated shop serves its own handlers, so the host owns its state. A server isitright did not
write owns its own, in a file or a SQLite database. An `ExternalServer` says how to start it and
how to move state in and out of its storage:

* ``seed`` writes a world's service state into the run directory in the server's format and
  returns the environment the server reads its location from;
* ``read`` reads the storage back as service state (the final-state export, hidden from the agent).

The proxy (`isitright.packs.mcp.proxy`) starts the server per run on the seeded copy, forwards the
agent's calls and records every one. The reference procedure runs against the same kind of server,
so roles are computed by the real thing. The server is never run on anything but a copy.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.model import ServiceState, ToolCallError, TraceDict
from isitright.packs.mcp.session import McpSession


class StateAdapter(Protocol):
    """Moves service state in and out of a server's storage."""

    def seed(self, service: ServiceState, directory: Path) -> dict[str, str]: ...

    def read(self, directory: Path) -> ServiceState: ...


@dataclass(frozen=True)
class ExternalServer:
    """How to start the third-party server on a seeded copy of a world."""

    command: str
    args: Sequence[str]
    adapter: StateAdapter
    env: Mapping[str, str] = field(default_factory=dict)

    def parameters(self, service: ServiceState, directory: Path) -> StdioServerParameters:
        """Seed ``directory`` and describe the process to start (``{dir}`` is substituted)."""
        directory.mkdir(parents=True, exist_ok=True)
        seeded = self.adapter.seed(service, directory)
        return StdioServerParameters(
            command=self.command,
            args=[a.replace("{dir}", str(directory)) for a in self.args],
            env={**self.env, **seeded},
        )


@dataclass(frozen=True)
class JsonLinesFile:
    """A file of JSON lines, one record per line, each with a ``type`` that names its collection.

    ``collections`` maps a service-state collection to the record type and the fields written.
    Keyed collections are dicts by key; the rest are lists. The server reads its path from
    ``env_var``. Lines of a type not listed are kept apart and written back unchanged.
    """

    filename: str
    env_var: str
    records: Mapping[str, str]
    """Collection name -> the ``type`` value of its lines."""
    keyed: Sequence[str] = ()
    key_field: str = "name"

    def seed(self, service: ServiceState, directory: Path) -> dict[str, str]:
        path = directory / self.filename
        lines = []
        for collection, kind in self.records.items():
            rows = service.get(collection, {} if collection in self.keyed else [])
            rows = list(rows.values()) if collection in self.keyed else list(rows)
            for row in rows:
                body = {k: v for k, v in row.items() if k != "id" or collection in self.keyed}
                lines.append(json.dumps({"type": kind, **body}, sort_keys=True))
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return {self.env_var: str(path)}

    def read(self, directory: Path) -> ServiceState:
        path = directory / self.filename
        out: ServiceState = {c: ({} if c in self.keyed else []) for c in self.records}
        by_kind = {kind: collection for collection, kind in self.records.items()}
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            collection = by_kind.get(row.pop("type", None))
            if collection is None:
                continue
            if collection in self.keyed:
                out[collection][row[self.key_field]] = row
            else:
                row["id"] = "|".join(str(row[k]) for k in sorted(row))
                out[collection].append(row)
        return out


@dataclass(frozen=True)
class SqliteFile:
    """A SQLite database the server opens. ``tables`` maps a table to its CREATE TABLE text.

    Service state is ``{table: [row, ...]}``. The server finds the file through ``env_var``, or
    through a ``{dir}`` / ``database`` placeholder in its arguments.
    """

    database: str
    tables: Mapping[str, str]
    env_var: str | None = None

    def seed(self, service: ServiceState, directory: Path) -> dict[str, str]:
        path = directory / self.database
        path.unlink(missing_ok=True)
        with closing(sqlite3.connect(path)) as connection, connection:
            for table, ddl in self.tables.items():
                connection.execute(ddl)
                for row in service.get(table, []):
                    names = list(row)
                    connection.execute(
                        f"INSERT INTO {table} ({', '.join(names)}) "
                        f"VALUES ({', '.join('?' for _ in names)})",
                        [row[n] for n in names],
                    )
        return {self.env_var: str(path)} if self.env_var else {}

    def read(self, directory: Path) -> ServiceState:
        path = directory / self.database
        out: ServiceState = {}
        with closing(sqlite3.connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            for table in self.tables:
                rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                out[table] = [dict(r) for r in rows]
        return out


class ExternalCaller:
    """A `Caller` over a live external server that records its calls like the proxy does."""

    def __init__(self, session: McpSession) -> None:
        self.session = session
        self.trace: list[TraceDict] = []

    def __call__(self, tool: str, **arguments: Any) -> dict[str, Any]:
        result = self.session.call_tool(tool, arguments)
        self.trace.append(
            {
                "index": len(self.trace),
                "name": tool,
                "arguments": arguments,
                "result": result.text,
                "is_error": result.is_error,
            }
        )
        if result.is_error:
            raise ToolCallError(result.text)
        if not result.text:
            return {}
        try:
            parsed = json.loads(result.text)
        except ValueError:
            return {"text": result.text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
