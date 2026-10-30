from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.host import HostTool, build_server
from isitright.packs.mcp.session import McpSession
from isitright.packs.mcp.trace import TraceRecorder

ADD = HostTool(
    "add",
    "Add two integers.",
    {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
)


def _handler(name: str, arguments: dict[str, Any]) -> str:
    if name == "add":
        return str(arguments["a"] + arguments["b"])
    raise ValueError(f"Tool '{name}' not found.")


@pytest.fixture
def served() -> Any:
    trace = TraceRecorder()
    session = McpSession(build_server("test", [ADD], _handler, trace))
    try:
        yield session, trace
    finally:
        session.close()


def test_lists_tools_with_schema(served: Any) -> None:
    session, _ = served
    [spec] = session.list_tools()
    assert spec.name == "add"
    assert spec.description == "Add two integers."
    assert spec.input_schema["required"] == ["a", "b"]


def test_call_returns_text_and_records_trace(served: Any) -> None:
    session, trace = served
    result = session.call_tool("add", {"a": 2, "b": 3})
    assert (result.text, result.is_error) == ("5", False)
    [event] = trace.events
    assert (event.index, event.name, event.arguments, event.result) == (
        0,
        "add",
        {"a": 2, "b": 3},
        "5",
    )
    assert trace.to_json()[0]["is_error"] is False


def test_handler_exception_becomes_error_result(served: Any) -> None:
    session, trace = served
    result = session.call_tool("missing", {})
    assert (result.text, result.is_error) == ("Tool 'missing' not found.", True)
    assert trace.events[-1].is_error is True


def test_close_is_idempotent() -> None:
    session = McpSession(build_server("test", [ADD], _handler, TraceRecorder()))
    session.close()
    session.close()
    with pytest.raises(Exception):  # noqa: B017 - any failure after close is acceptable
        session.call_tool("add", {"a": 1, "b": 1})


def test_trace_callback_sees_every_event() -> None:
    seen: list[str] = []
    trace = TraceRecorder(on_record=lambda e: seen.append(f"{e.index}:{e.name}:{e.is_error}"))
    session = McpSession(build_server("test", [ADD], _handler, trace))
    try:
        session.call_tool("add", {"a": 1, "b": 1})
        session.call_tool("missing", {})
    finally:
        session.close()
    assert seen == ["0:add:False", "1:missing:True"]


def test_stdio_subprocess_round_trip(tmp_path: Path) -> None:
    script = tmp_path / "serve.py"
    script.write_text(
        "from isitright.packs.mcp.host import HostTool, build_server, serve_stdio\n"
        "from isitright.packs.mcp.trace import TraceRecorder\n"
        "spec = HostTool('add', 'Add.', {'type': 'object', 'properties': {}})\n"
        "def handler(name, arguments):\n"
        "    if name != 'add':\n"
        "        raise ValueError('no such tool')\n"
        "    return str(arguments['a'] + arguments['b'])\n"
        "serve_stdio(build_server('t', [spec], handler, TraceRecorder()))\n",
        encoding="utf-8",
    )
    session = McpSession(StdioServerParameters(command=sys.executable, args=[str(script)]))
    try:
        assert [t.name for t in session.list_tools()] == ["add"]
        assert session.call_tool("add", {"a": 4, "b": 5}).text == "9"
        assert session.call_tool("nope", {}).is_error is True
    finally:
        session.close()
