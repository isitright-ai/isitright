# Proposed fixture: pending owner review
"""Scripted agents (no model) for the airline scenario. ``AIRLINE_AGENT_MODE``:

    careful   the oracle's reference procedure (the policy's "Cancel flight" section), run through
              the injected MCP host like any agent
    careless  cancels the reservation straight away, without checking anything
    refuse    lists the tools and does nothing

Written by the same author as the oracle, so "careful" agrees with the oracle by construction.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.model import ToolCallError
from isitright.packs.mcp.session import McpSession


def main() -> None:
    import scenario

    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    session = McpSession(StdioServerParameters(**config["mcpServers"]["isitright"]))
    mode = os.environ.get("AIRLINE_AGENT_MODE", "careful")
    reservation = (
        os.environ.get("AIRLINE_RESERVATION")
        or scenario.DEFAULT_RESERVATIONS[os.environ.get("AIRLINE_TASK_ID", "1")]
    )

    def call(tool: str, **arguments: Any) -> dict[str, Any]:
        result = session.call_tool(tool, arguments)
        if result.is_error:
            raise ToolCallError(result.text)
        try:
            parsed = json.loads(result.text)
        except ValueError:
            return {"text": result.text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    try:
        session.list_tools()
        if mode == "careless":
            call("cancel_reservation", reservation_id=reservation)
        elif mode == "careful":
            scenario.SCENARIO.oracle.reference(call)
    finally:
        session.close()


if __name__ == "__main__":
    main()
