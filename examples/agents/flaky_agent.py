"""A deliberately flaky scripted agent for the booking scenario: no model, simulated cost.

It is careful on odd trials and careless on even trials, where the trial number is the last part of
``ISITRIGHT_RUN_DIR`` (the runner names run directories ``runs/<world>/<trial>``). So the same world
passes and fails across runs, and a baseline of four runs is itself flaky. Each run writes a
``transcript.json`` that reports a simulated cost of ``FLAKY_AGENT_COST`` (default 0.1) per run, so
the money budget and the run counts can be tested without any API key or network.
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
    run_dir = Path(os.environ["ISITRIGHT_RUN_DIR"])
    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    server = StdioServerParameters(**config["mcpServers"]["isitright"])
    careless = int(run_dir.name) % 2 == 0
    async with Client(server, mode="legacy") as client:

        async def call(name: str, **arguments: str) -> str:
            result = await client.call_tool(name, arguments)
            return "".join(c.text for c in result.content if hasattr(c, "text"))

        booking = json.loads(await call("get_booking", booking_id="B100"))
        if careless:
            await call("cancel_booking", booking_id="B100")
        else:
            age = datetime(2024, 5, 15, 15, 0) - datetime.fromisoformat(booking["created_at"])
            segment = booking["segments"][0]
            status = await call("get_flight_status", flight=segment["flight"], date=segment["date"])
            if age < timedelta(hours=24) or status == "cancelled" or booking["cabin"] == "business":
                await call("cancel_booking", booking_id="B100")
    cost = float(os.environ.get("FLAKY_AGENT_COST", "0.1"))
    (run_dir / "transcript.json").write_text(
        json.dumps(
            {
                "provider": "scripted",
                "model": "flaky",
                "settings": {"careless_on_even_trials": True},
                "usage": [{"input_tokens": 100, "output_tokens": 10, "cost": cost}],
                "stop_reason": "final",
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
