"""Serve a fixed set of tools over MCP and record every call.

The host knows nothing about any domain. A caller supplies tool specs and a handler that executes
one call against the caller's own state, and gets back an MCP ``Server`` plus a ``TraceRecorder``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anyio
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from isitright.packs.mcp.trace import TraceRecorder


@dataclass(frozen=True)
class HostTool:
    """A tool as listed to the agent: name, description and a JSON Schema for its arguments."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


ToolHandler = Callable[[str, dict[str, Any]], str]
"""Executes one call and returns its result text. Any exception becomes an MCP error result."""


AfterCall = Callable[[str, dict[str, Any], bool], None]
"""Runs after a call's own trace event is recorded and before the result reaches the agent, with
the tool name, its arguments and whether it was an error. Anything it records follows that call."""


def build_server(
    name: str,
    tools: Sequence[HostTool],
    handler: ToolHandler,
    trace: TraceRecorder,
    after_call: AfterCall | None = None,
) -> Server[Any]:
    """Build an MCP server that lists ``tools`` and routes calls to ``handler``, with a trace."""
    listed = [
        types.Tool(
            name=spec.name, description=spec.description, input_schema=dict(spec.input_schema)
        )
        for spec in tools
    ]

    async def on_list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=listed)

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        arguments = dict(params.arguments or {})
        try:
            text = handler(params.name, arguments)
            is_error = False
        except Exception as exc:
            text = str(exc)
            is_error = True
        trace.record(params.name, arguments, text, is_error=is_error)
        if after_call is not None:
            after_call(params.name, arguments, is_error)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)], is_error=is_error
        )

    return Server(name, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def serve_stdio(server: Server[Any]) -> None:
    """Serve ``server`` over this process's stdin/stdout until the client disconnects.

    stdout carries the protocol, so nothing else in the process may print to it.
    """

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(run)
