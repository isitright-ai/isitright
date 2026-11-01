"""The SDK interface and turn driver, against a fake SDK agent and a scripted user."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ADAPTER = Path(__file__).parents[1] / "examples" / "agents" / "tau2_openai"
sys.path.insert(0, str(ADAPTER))

from sdk import AgentTurn, Usage, converse, write_transcript  # noqa: E402


class FakeAgent:
    """Answers each message and calls a tool on the second turn, reporting usage like an SDK."""

    def __init__(self) -> None:
        self.heard: list[str] = []
        self.closed = False

    def respond(self, user_message: str) -> AgentTurn:
        self.heard.append(user_message)
        calls = ("get_reservation_details",) if len(self.heard) == 2 else ()
        return AgentTurn(f"reply {len(self.heard)}", calls, (Usage(100, 10), Usage(50, 5)))

    def close(self) -> None:
        self.closed = True


class ScriptedUser:
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.heard: list[str] = []

    def next_message(self, agent_text: str) -> str | None:
        self.heard.append(agent_text)
        return self.lines.pop(0) if self.lines else None


def test_the_user_and_the_agent_take_turns_until_the_user_stops() -> None:
    agent, user = FakeAgent(), ScriptedUser(["cancel my booking", "yes, confirm"])
    conversation = converse(agent, user)
    assert agent.heard == ["cancel my booking", "yes, confirm"]
    assert user.heard == ["Hi! How can I help you today?", "reply 1", "reply 2"]
    assert conversation.stop_reason == "final"
    assert [t.tool_calls for t in conversation.turns] == [(), ("get_reservation_details",)]
    assert len(conversation.usage) == 4


def test_a_conversation_that_does_not_end_stops_at_the_turn_cap() -> None:
    user = ScriptedUser(["again"] * 10)
    conversation = converse(FakeAgent(), user, max_turns=3)
    assert len(conversation.turns) == 3 and conversation.stop_reason == "max_turns"


def test_the_transcript_carries_the_stack_the_usage_and_a_cost_only_for_a_priced_model(
    tmp_path: Path,
) -> None:
    conversation = converse(FakeAgent(), ScriptedUser(["a", "b"]))
    write_transcript(
        tmp_path,
        provider="openai",
        model="m1",
        conversation=conversation,
        prices_per_million={"m1": (1.0, 2.0)},
        sdk_versions={"openai-agents": "1.2.3"},
    )
    data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert (data["provider"], data["model"], data["stop_reason"]) == ("openai", "m1", "final")
    assert data["sdk_versions"] == {"openai-agents": "1.2.3"}
    assert [u["input_tokens"] for u in data["usage"]] == [100, 50, 100, 50]
    assert data["usage"][0]["cost"] == pytest.approx((100 * 1.0 + 10 * 2.0) / 1e6)
    write_transcript(
        tmp_path,
        provider="openai",
        model="unpriced",
        conversation=conversation,
        prices_per_million={"m1": (1.0, 2.0)},
    )
    unpriced = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert all("cost" not in u for u in unpriced["usage"])  # no price: no cost, no guess


def test_the_runner_reads_this_transcript_and_refuses_a_money_budget_without_cost(
    tmp_path: Path,
) -> None:
    from isitright.packs.mcp.runner import read_transcript

    conversation = converse(FakeAgent(), ScriptedUser(["a"]))
    write_transcript(
        tmp_path,
        provider="openai",
        model="m1",
        conversation=conversation,
        prices_per_million={"m1": (1.0, 2.0)},
    )
    extra = read_transcript(tmp_path, (None, None))
    assert extra["money"] == pytest.approx((100 + 20 + 50 + 10) / 1e6)
    assert extra["model_calls"] == 2 and extra["subject"]["provider"] == "openai"
    write_transcript(
        tmp_path,
        provider="openai",
        model="free",
        conversation=conversation,
        prices_per_million={},
    )
    assert "money" not in read_transcript(tmp_path, (None, None))


def test_a_one_shot_user_gives_the_task_once_and_then_ends_the_conversation() -> None:
    from sdk import OneShotUser

    agent = FakeAgent()
    conversation = converse(agent, OneShotUser("delete the drafts"))
    assert agent.heard == ["delete the drafts"] and conversation.stop_reason == "final"
    assert len(conversation.turns) == 1


def test_the_conversation_is_written_for_a_reviewer(tmp_path: Path) -> None:
    from sdk import write_conversation

    conversation = converse(FakeAgent(), ScriptedUser(["cancel", "yes"]))
    write_conversation(tmp_path, conversation)
    data = json.loads((tmp_path / "conversation.json").read_text(encoding="utf-8"))
    assert [t["user"] for t in data["turns"]] == ["cancel", "yes"]
    assert data["turns"][1]["tool_calls"] == ["get_reservation_details"]
    assert data["turns"][0]["agent"] == "reply 1" and data["stop_reason"] == "final"
