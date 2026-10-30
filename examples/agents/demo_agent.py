"""A scripted stand-in for an agent: it speaks MCP to the scenario server, with no model.

It reads the MCP configuration from ``ISITRIGHT_MCP_CONFIG`` and behaves according to
``DEMO_AGENT_MODE``:

    careless  looks up the booking and cancels it whatever the policy says
    refuse    looks up the booking and never cancels
    careful   applies the policy: checks booking age and the flight status, then acts

It exists so the quick start and the tests need no API key. A real agent replaces it by accepting
the same ``mcp.json`` (the standard ``mcpServers`` format) and the task text in ``task.txt``.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


async def main() -> None:
    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    server = StdioServerParameters(**config["mcpServers"]["isitright"])
    mode = os.environ.get("DEMO_AGENT_MODE", "careful")
    async with Client(server, mode="legacy") as client:

        async def call(name: str, **arguments: str) -> str:
            result = await client.call_tool(name, arguments)
            return "".join(c.text for c in result.content if hasattr(c, "text"))

        booking = json.loads(await call("get_booking", booking_id="B100"))
        if mode == "careless":
            await call("cancel_booking", booking_id="B100")
        elif mode == "careful":
            age = datetime(2024, 5, 15, 15, 0) - datetime.fromisoformat(booking["created_at"])
            segment = booking["segments"][0]
            status = await call("get_flight_status", flight=segment["flight"], date=segment["date"])
            if age < timedelta(hours=24) or status == "cancelled" or booking["cabin"] == "business":
                await call("cancel_booking", booking_id="B100")


if __name__ == "__main__":
    asyncio.run(main())
