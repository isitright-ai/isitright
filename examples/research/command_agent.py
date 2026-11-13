# Proposed fixture: pending owner review
# A scripted agent (written by Claude, not a real research agent) that talks to the isitright
# research server over MCP stdio, the way a real agent command would. It shows the agent-command
# contract: read the MCP config and the question, use only `search` and `open`, write report.json.
"""Usage (isitright substitutes the braces):

python command_agent.py --task task.json --mode careful {mcp_config} {run_dir}
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.session import McpSession
from isitright.packs.research.agents import STAND_INS, ResearchTask, ToolClient


class McpTools(ToolClient):
    """The same two calls as the in-process client, made over a real MCP connection."""

    def __init__(self, session: McpSession) -> None:
        self._session = session

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        result = self._session.call_tool("search", {"query": query, "k": k})
        rows: list[dict[str, Any]] = [] if result.is_error else json.loads(result.text)["results"]
        return rows

    def open(self, doc_id: str) -> dict[str, Any] | None:
        result = self._session.call_tool("open", {"id": doc_id})
        value: dict[str, Any] | None = None if result.is_error else json.loads(result.text)
        return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--mode", default="careful", choices=["careful", "credulous"])
    parser.add_argument("mcp_config", type=Path)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    task = ResearchTask.model_validate_json(args.task.read_text(encoding="utf-8"))
    server = json.loads(args.mcp_config.read_text(encoding="utf-8"))["mcpServers"]["isitright"]
    session = McpSession(
        StdioServerParameters(command=server["command"], args=server["args"], env=dict(os.environ))
    )
    try:
        report = STAND_INS[args.mode](task).run(McpTools(session), task, 0)
    finally:
        session.close()
    (args.run_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
