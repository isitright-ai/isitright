"""MCP pack: audit tool-using agents against perturbed worlds served over MCP.

Declare a scenario (`McpScenario`): an entity schema, constraints, tools with simulated handlers,
service parameters, hints and an oracle. `run_scenario` generates the valid worlds with the core's
families, computes each world's role with the scenario's reference procedure, serves each world to
any agent command that accepts an MCP configuration, and reports counts against a baseline.

The MCP SDK is needed only to serve or call tools, so those parts import it lazily; declaring a
scenario and generating worlds work without it.
"""

from __future__ import annotations

import importlib
from typing import Any

from isitright.core.entities import EntitySchema, ModelError
from isitright.core.hints import Hint, HintKind, register_hint_kind


def _check_trace(schema: EntitySchema, hint: Hint) -> None:
    calls = hint.args.get("calls")
    if not isinstance(calls, list) or any(
        not isinstance(c, dict) or "tool" not in c for c in calls
    ):
        raise ModelError(f"hint {hint.name!r} (trace) needs calls: a list of {{tool, arguments}}")


register_hint_kind(HintKind("trace", _check_trace))

_LAZY = {
    "AgentsInputError": "isitright.packs.mcp.audit",
    "run_scenario": "isitright.packs.mcp.audit",
    "replay_report": "isitright.packs.mcp.replay",
    **{
        name: "isitright.packs.mcp.model"
        for name in (
            "Expectation",
            "FixedWorld",
            "Interference",
            "Invariant",
            "Layout",
            "McpScenario",
            "ScenarioError",
            "ScenarioOracle",
            "ToolCallError",
            "ToolDef",
            "load_scenario",
        )
    },
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
