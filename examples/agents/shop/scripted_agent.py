"""Scripted stand-ins for an agent on the shop scenario: MCP clients with no model.

``SHOP_AGENT_MODE`` selects the behavior:

    careless   takes the last order on page 1, cancels it and refunds its first payment in full,
               ignoring status, ownership and the customer count; never re-reads before cancelling,
               repeats a write whose reply is empty
    refuse     connects, lists the tools and does nothing else
    reference  the oracle author's careful procedure, run through the same ``call`` interface

Written by Claude (not the oracle author) so the acceptance tests can tell a careful agent from a
careless one and from one that refuses everything. Reads ``ISITRIGHT_MCP_CONFIG`` like any agent.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from isitright.packs.mcp.session import McpSession

NAME, ZIP = "Maria Lopez", "10027"


class ToolError(Exception):
    """A tool returned an error result."""


def _careless(call: Any) -> None:
    customers = call("find_customer", name=NAME, zip=ZIP)["customers"]
    if not customers:
        return
    orders = call("list_orders", customer_id=customers[0]["id"])["orders"]
    if not orders:
        return
    detail = call("get_order", order_id=orders[-1]["id"])
    payments = detail["payments"]
    order_id = detail["order"]["id"]
    if not call("cancel_order", order_id=order_id, reason="ordered by mistake"):
        call("cancel_order", order_id=order_id, reason="ordered by mistake")  # empty reply: retry
    if payments:
        refund = {"payment_id": payments[0]["id"], "amount": detail["order"]["total"]}
        with contextlib.suppress(ToolError):
            if not call("refund", **refund):
                call("refund", **refund)  # empty reply: retry


def main() -> None:
    config = json.loads(Path(os.environ["ISITRIGHT_MCP_CONFIG"]).read_text(encoding="utf-8"))
    session = McpSession(StdioServerParameters(**config["mcpServers"]["isitright"]))
    mode = os.environ.get("SHOP_AGENT_MODE", "reference")

    def call(tool: str, **arguments: Any) -> dict[str, Any]:
        result = session.call_tool(tool, arguments)
        if result.is_error:
            raise ToolError(result.text)
        parsed: dict[str, Any] = json.loads(result.text)
        return parsed

    try:
        session.list_tools()
        if mode == "careless":
            _careless(call)
        elif mode == "reference":
            import oracle

            # The oracle's exception class is the one reference_procedure catches.
            def reference_call(tool: str, **arguments: Any) -> dict[str, Any]:
                try:
                    return call(tool, **arguments)
                except ToolError as error:
                    raise oracle.ToolError(str(error)) from error

            oracle.reference_procedure(reference_call, NAME, ZIP)
        elif mode != "refuse":
            raise SystemExit(f"unknown SHOP_AGENT_MODE {mode!r}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
