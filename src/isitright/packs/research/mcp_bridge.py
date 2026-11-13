"""The MCP wrapper of the corpus tools: the generic host of the MCP pack over a `ToolHost`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from isitright.packs.mcp.host import HostTool, build_server
from isitright.packs.mcp.trace import TraceEvent, TraceRecorder
from isitright.packs.research.retrieval import ToolHost


def make_server(host: ToolHost, run_dir: Path, schemas: dict[str, dict[str, Any]]) -> Any:
    """An MCP server that lists `search` and `open` and routes calls to ``host``.

    The host already refuses any other tool name; the listing offers only the two. Every call is
    appended to ``trace.jsonl`` in ``run_dir``, in the format the audit reads back.
    """
    trace_path = run_dir / "trace.jsonl"
    tools = [
        HostTool(name, spec["description"], spec["input_schema"]) for name, spec in schemas.items()
    ]

    def persist(event: TraceEvent) -> None:
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.__dict__, sort_keys=True, default=str) + "\n")

    def handler(name: str, arguments: dict[str, Any]) -> str:
        return host.call(name, arguments)

    return build_server("isitright-research", tools, handler, TraceRecorder(on_record=persist))
