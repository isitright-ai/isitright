# Proposed fixture: pending owner review
"""Scripted agents for the notes scenario (no model). ``NOTES_AGENT_MODE``:

reference  deletes every note whose text contains "draft", ignoring capitalization
careless   deletes only the first note that contains "draft" (a bug the oracle should catch)
refuse     lists the tools and does nothing
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.session import McpSession


def main() -> None:
    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    session = McpSession(StdioServerParameters(**config["mcpServers"]["isitright"]))
    mode = os.environ.get("NOTES_AGENT_MODE", "reference")
    try:
        session.list_tools()
        if mode == "refuse":
            return
        notes = json.loads(session.call_tool("list_notes", {}).text)["notes"]
        drafts = [n for n in notes if "draft" in n["text"].lower()]
        for note in drafts[:1] if mode == "careless" else drafts:
            session.call_tool("delete_note", {"note_id": note["id"]})
    finally:
        session.close()


if __name__ == "__main__":
    main()
