# Proposed fixture: pending owner review
"""The narrow interface between isitright's runner and an agent SDK, and the turn driver.

An SDK agent answers one user message at a time and calls MCP tools itself, over the stdio host
that isitright injects (``ISITRIGHT_MCP_CONFIG``). Everything SDK-specific sits behind `SdkAgent`:
the OpenAI Agents SDK adapter is `openai_agents_adapter.OpenAIAgentsAdapter`; another SDK needs
only another class with the same two methods. A user simulator (the one from tau2, behind
`tau2_bridge.Tau2UserBridge`, or a scripted one) sits behind `UserSimulator`.

`converse` drives the two turn by turn, and `write_transcript` records the stack and the usage in
the `transcript.json` that `isitright agents run` reads (provider, model, per-call usage and cost),
which is what lets `--max-money` work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AgentTurn:
    """One reply: its text, the tools the SDK called while producing it, and the model usage."""

    text: str
    tool_calls: tuple[str, ...] = ()
    usage: tuple[Usage, ...] = ()
    """One entry per model call made for this reply."""


class SdkAgent(Protocol):
    def respond(self, user_message: str) -> AgentTurn: ...

    def close(self) -> None: ...


class UserSimulator(Protocol):
    def next_message(self, agent_text: str) -> str | None:
        """The user's reply to the agent, or None when the user ends the conversation."""
        ...


class OneShotUser:
    """A user who says one thing (the task text) and then ends the conversation. It needs no model,
    so the SDK adapter can be tried on its own, without tau2."""

    def __init__(self, message: str) -> None:
        self._message: str | None = message

    def next_message(self, agent_text: str) -> str | None:
        message, self._message = self._message, None
        return message


@dataclass
class Conversation:
    turns: list[AgentTurn] = field(default_factory=list)
    user_messages: list[str] = field(default_factory=list)
    stop_reason: str = "final"

    @property
    def usage(self) -> list[Usage]:
        return [u for turn in self.turns for u in turn.usage]


def converse(
    agent: SdkAgent,
    user: UserSimulator,
    *,
    greeting: str = "Hi! How can I help you today?",
    max_turns: int = 30,
) -> Conversation:
    """The user speaks after the greeting; the agent answers; until the user stops or the cap."""
    conversation = Conversation()
    heard = greeting
    for _ in range(max_turns):
        message = user.next_message(heard)
        if message is None:
            return conversation
        conversation.user_messages.append(message)
        turn = agent.respond(message)
        conversation.turns.append(turn)
        heard = turn.text
    conversation.stop_reason = "max_turns"
    return conversation


def write_conversation(run_dir: Path, conversation: Conversation) -> None:
    """``conversation.json``: what was said and which tools the agent called after each message.

    The runner does not read it. It is there so a reviewer can see why a run went the way it did
    (for example whether the simulated customer gave a reason the oracle did not assume).
    """
    rows = [
        {"user": user, "agent": turn.text, "tool_calls": list(turn.tool_calls)}
        for user, turn in zip(conversation.user_messages, conversation.turns, strict=False)
    ]
    (run_dir / "conversation.json").write_text(
        json.dumps({"stop_reason": conversation.stop_reason, "turns": rows}, indent=1),
        encoding="utf-8",
    )


def write_transcript(
    run_dir: Path,
    *,
    provider: str,
    model: str,
    conversation: Conversation,
    prices_per_million: Mapping[str, tuple[float, float]],
    sdk_versions: Mapping[str, str] | None = None,
    settings: Mapping[str, object] | None = None,
) -> None:
    """``transcript.json`` for the runner. Cost is tokens times the price (input, output per
    million tokens) the caller states; an unknown model gives no cost, and a money budget is then
    refused rather than guessed."""
    price = prices_per_million.get(model)
    usage = [
        {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            **(
                {"cost": (u.input_tokens * price[0] + u.output_tokens * price[1]) / 1_000_000}
                if price is not None
                else {}
            ),
        }
        for u in conversation.usage
    ]
    (run_dir / "transcript.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "model": model,
                "sdk_versions": dict(sdk_versions or {}),
                "settings": dict(settings or {}),
                "usage": usage,
                "stop_reason": conversation.stop_reason,
            }
        ),
        encoding="utf-8",
    )
