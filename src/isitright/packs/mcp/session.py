"""A synchronous client session onto an MCP server.

Agent harnesses such as tau2 are synchronous, while the MCP SDK is asyncio. The session owns a
private event loop on a daemon thread, connects a client to the server (in-memory streams, or a
stdio subprocess) with a real initialize handshake and JSON-RPC framing, and exposes blocking calls.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from mcp import types
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server import Server

from isitright.packs.mcp.host import HostTool

_T = TypeVar("_T")
_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ToolResult:
    """The text of a tool call result and whether the server flagged it as an error."""

    text: str
    is_error: bool


class McpSession:
    """Blocking facade over an MCP client. Call ``close`` when done.

    ``server`` is either an in-process ``Server`` (connected over in-memory streams) or
    ``StdioServerParameters`` (a subprocess is spawned and spoken to over stdin/stdout).
    """

    def __init__(self, server: Server[Any] | StdioServerParameters) -> None:
        self._server = server
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._client: Client | None = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, name="isitright-mcp-session", daemon=True)
        self._thread.start()
        if not self._ready.wait(_TIMEOUT_SECONDS):
            raise RuntimeError("MCP session did not start within the time limit")
        if self._error is not None:
            raise RuntimeError("MCP session failed to start") from self._error

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())
        self._loop.close()

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with Client(self._server, mode="legacy") as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:
            self._error = exc
        finally:
            self._client = None
            self._ready.set()

    def _submit(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(_TIMEOUT_SECONDS)

    def list_tools(self) -> list[HostTool]:
        """List every tool the server offers, following pagination."""
        client = self._require_client()

        async def collect() -> list[types.Tool]:
            tools: list[types.Tool] = []
            cursor: str | None = None
            while True:
                page = await client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    return tools

        return [
            HostTool(tool.name, tool.description or "", tool.input_schema)
            for tool in self._submit(collect())
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool and return its concatenated text content."""
        client = self._require_client()
        result = self._submit(client.call_tool(name, arguments))
        text = "".join(c.text for c in result.content if isinstance(c, types.TextContent))
        return ToolResult(text, bool(result.is_error))

    def close(self) -> None:
        """Stop the session. Safe to call more than once."""
        if self._stop is not None and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=10)

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("MCP session is not connected")
        return self._client
