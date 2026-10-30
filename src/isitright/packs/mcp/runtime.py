"""The simulated service for one world: handlers, response middleware and timing.

One runtime is one fresh world. The serve process uses it live; the reference procedure, role
computation and offline replay use it in-process, so all of them see exactly the same service.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from isitright.core.mutations import (
    ResponseEdit,
    Timer,
    World,
    apply_edits,
    edits_to_json,
)
from isitright.packs.mcp.model import (
    Interference,
    McpScenario,
    ServiceState,
    ToolCallError,
    render,
)


@dataclass
class ServiceRuntime:
    """A world's service state plus the edits that act on it while it runs."""

    scenario: McpScenario
    service: ServiceState
    response_edits: tuple[ResponseEdit, ...] = ()
    timers: tuple[Timer, ...] = ()
    interferences: tuple[Interference, ...] = ()
    _state_keys: dict[str, str] = field(default_factory=dict)
    _successes: dict[str, int] = field(default_factory=dict)
    _fired: set[str] = field(default_factory=set)

    @staticmethod
    def for_world(
        scenario: McpScenario, world: World, interferences: tuple[Interference, ...] = ()
    ) -> ServiceRuntime:
        return ServiceRuntime(
            scenario,
            scenario.layout.to_service(world.state),
            world.response_edits,
            world.timers,
            interferences,
            dict(world.state.keys),
        )

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Run one tool call; raises on a tool error. The response middleware applies on success."""
        tool = self.scenario.tool(name)
        if tool is None:
            raise ValueError(f"Tool '{name}' not found.")
        result = tool.handler(self.service, arguments)
        first = self._successes.get(name, 0) == 0
        self._successes[name] = self._successes.get(name, 0) + 1
        for edit in self.response_edits:
            if edit.tool == name and (first or not edit.first_only):
                result = apply_response_edit(edit, result)
        return render(result)

    def after_call(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Fire timers and interferences that match a successful call; describe each change."""
        changes: list[dict[str, Any]] = []
        for timer in self.timers:
            if timer.name not in self._fired and timer.trigger.matches(name, arguments):
                self._fired.add(timer.name)
                before = self.scenario.layout.from_service(self.service, self._state_keys)
                after = apply_edits(before, timer.edits)
                self.service = self.scenario.layout.to_service(after)
                changes.append(timer.record or {"edits": edits_to_json(timer.edits)})
        for interference in self.interferences:
            if interference.name not in self._fired and interference.when(
                self.service, name, arguments
            ):
                self._fired.add(interference.name)
                changes.append(interference.apply(self.service))
        return changes


def apply_response_edit(edit: ResponseEdit, result: Any) -> Any:
    """What the agent is told, given an edit. The state underneath is unchanged."""
    if edit.op == "empty_ack":
        return {}
    if edit.op == "error":
        raise ValueError(edit.declares or "the service reported an error")
    if not isinstance(result, dict) or edit.field is None:
        return result
    changed = copy.deepcopy(result)
    if edit.op == "drop_field":
        changed[edit.field] = [] if isinstance(changed.get(edit.field), list) else None
    elif edit.op == "reorder" and isinstance(changed.get(edit.field), list):
        changed[edit.field] = list(reversed(changed[edit.field]))
    return changed


class RuntimeCaller:
    """A `Caller` over a runtime that records the calls it makes, like the serve process."""

    def __init__(self, runtime: ServiceRuntime) -> None:
        self.runtime = runtime
        self.trace: list[dict[str, Any]] = []

    def __call__(self, tool: str, **arguments: Any) -> dict[str, Any]:
        try:
            text = self.runtime.call(tool, arguments)
            is_error = False
        except Exception as error:
            text, is_error = str(error), True
        self.trace.append(
            {
                "index": len(self.trace),
                "name": tool,
                "arguments": arguments,
                "result": text,
                "is_error": is_error,
            }
        )
        if is_error:
            raise ToolCallError(text)
        for change in self.runtime.after_call(tool, arguments):
            self.trace.append(
                {
                    "index": len(self.trace),
                    "name": "__world_change__",
                    "arguments": change,
                    "result": "",
                    "is_error": False,
                }
            )
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
