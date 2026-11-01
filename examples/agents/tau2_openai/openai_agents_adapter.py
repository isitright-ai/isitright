"""The OpenAI Agents SDK behind `SdkAgent`. Needs the SDK and a key; no test runs it.

Install it yourself (it is not an isitright dependency): ``pip install openai-agents``. The key is
read by the SDK from ``OPENAI_API_KEY`` when a run starts and is never stored here. The MCP server
is the stdio host from ``ISITRIGHT_MCP_CONFIG``, so the agent reaches the perturbed world only
through isitright's host (which fails closed on tools it does not serve).

Written against the SDK's documented API (``Agent``, ``Runner.run``, ``MCPServerStdio``,
``RunResult.to_input_list``) without running it: the owner's first run is its first test.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from sdk import AgentTurn, Usage

# Model calls allowed for one user message. The SDK's own default is 10, which a task that checks
# many reservations before answering can exceed.
DEFAULT_MAX_TURNS = 30


class OpenAIAgentsAdapter:
    def __init__(
        self, mcp_config: Path, instructions: str, model: str, max_turns: int = DEFAULT_MAX_TURNS
    ) -> None:
        self.max_turns = max_turns
        import agents  # imported late: the SDK is the owner's to install
        from agents.mcp import MCPServerStdio

        entry = json.loads(mcp_config.read_text(encoding="utf-8"))["mcpServers"]["isitright"]
        # The SDK's default is 5 seconds for each MCP request, which includes the server's start-up:
        # a scenario that imports a large package (tau2) can take longer when the machine is busy.
        timeout = float(os.environ.get("ISITRIGHT_MCP_TIMEOUT", "60"))
        self._server = MCPServerStdio(
            params={"command": entry["command"], "args": entry["args"]},
            cache_tools_list=True,
            client_session_timeout_seconds=timeout,
        )
        self._agents = agents
        self._agent = agents.Agent(
            name="agent", instructions=instructions, model=model, mcp_servers=[self._server]
        )
        self._history: list[Any] = []
        self._connected = False
        self._loop = asyncio.new_event_loop()

    def _run(self, text: str) -> Any:
        async def go() -> Any:
            if not self._connected:
                await self._server.connect()
                self._connected = True
            return await self._agents.Runner.run(
                self._agent,
                [*self._history, {"role": "user", "content": text}],
                max_turns=self.max_turns,
            )

        return self._loop.run_until_complete(go())

    def respond(self, user_message: str) -> AgentTurn:
        result = self._run(user_message)
        self._history = result.to_input_list()
        calls = tuple(
            str(getattr(getattr(item, "raw_item", item), "name", ""))
            for item in result.new_items
            if type(item).__name__ == "ToolCallItem"
        )
        usage = tuple(
            Usage(r.usage.input_tokens, r.usage.output_tokens) for r in result.raw_responses
        )
        return AgentTurn(str(result.final_output or ""), calls, usage)

    def close(self) -> None:
        if self._connected:
            self._loop.run_until_complete(self._server.cleanup())
        self._loop.close()
