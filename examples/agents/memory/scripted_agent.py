# Proposed fixture: pending owner review
"""Scripted agents (no model) for the Memory-server scenario. ``MEMORY_AGENT_MODE``:

reference  reads Alice's entity, removes the old fact if present, adds the new one if absent
careless   adds the new fact without reading or removing the old one
refuse     lists the tools and does nothing
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.session import McpSession

NAME, OLD, NEW = "Alice Chen", "works at Acme Corp", "works at Beta Corp"


def main() -> None:
    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    session = McpSession(StdioServerParameters(**config["mcpServers"]["isitright"]))
    mode = os.environ.get("MEMORY_AGENT_MODE", "reference")

    def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = session.call_tool(tool, arguments)
        return json.loads(result.text) if result.text and not result.is_error else {}

    try:
        session.list_tools()
        if mode == "refuse":
            return
        if mode == "careless":
            call("add_observations", {"observations": [{"entityName": NAME, "contents": [NEW]}]})
            return
        graph = call("search_nodes", {"query": NAME})
        people = [e for e in graph.get("entities", []) if e["name"] == NAME]
        if not people:
            entity = {"name": NAME, "entityType": "person", "observations": [NEW]}
            call("create_entities", {"entities": [entity]})
            return
        seen = people[0]["observations"]
        if OLD in seen:
            deletion = {"entityName": NAME, "observations": [OLD]}
            call("delete_observations", {"deletions": [deletion]})
        if NEW not in seen:
            call("add_observations", {"observations": [{"entityName": NAME, "contents": [NEW]}]})
    finally:
        session.close()


if __name__ == "__main__":
    main()
