"""The tau2 user simulator behind `UserSimulator`, so it can talk to an SDK agent turn by turn.

The simulator is a model (it needs its own key); this file only adapts tau2's message objects. It
needs tau2 installed (``pip install -e <tau2-bench checkout>``) and is written against tau2's
``UserSimulator`` (``get_init_state``, ``generate_next_message``, ``is_stop``) without being run
here: the owner's first real run is its first test.
"""

from __future__ import annotations

from typing import Any

from sdk import UserUsage


class Tau2UserBridge:
    def __init__(self, task: Any, llm: str, llm_args: dict[str, Any] | None = None) -> None:
        from tau2.data_model.message import AssistantMessage
        from tau2.user.user_simulator import UserSimulator

        instructions = str(task.user_scenario.instructions)
        self._simulator = UserSimulator(llm=llm, instructions=instructions, llm_args=llm_args)
        self._state = self._simulator.get_init_state()
        self._assistant = AssistantMessage
        self.last_usage: UserUsage | None = None

    def next_message(self, agent_text: str) -> str | None:
        message = self._assistant(role="assistant", content=agent_text)
        reply, self._state = self._simulator.generate_next_message(message, self._state)
        usage = getattr(reply, "usage", None) or {}
        cost = getattr(reply, "cost", None)
        # litellm names the counts prompt_tokens and completion_tokens
        self.last_usage = UserUsage(
            int(usage.get("prompt_tokens", usage.get("input_tokens", 0))),
            int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
            float(cost) if cost is not None else None,
        )
        if self._simulator.is_stop(reply):
            return None
        return str(reply.content)
