"""An isitright agent command: the OpenAI Agents SDK agent talking to the tau2 user simulator.

    isitright agents run --trust-code --scenario <a tau2 scenario> ^
        --agent-command "python examples/agents/tau2_openai/run_agent.py --task-id 1"

Reads ``ISITRIGHT_MCP_CONFIG`` and ``ISITRIGHT_RUN_DIR`` like any agent, drives the conversation
with `sdk.converse`, and writes ``transcript.json`` with the usage and cost. Environment (names
only): ``OPENAI_API_KEY`` for the agent and the user simulator; ``ISITRIGHT_AGENT_MODEL`` and
``ISITRIGHT_USER_MODEL`` (model names); ``ISITRIGHT_AGENT_MAX_TURNS`` (model calls per user
message, default 30; the SDK's own default of 10 is too low for some tasks);
``ISITRIGHT_PRICES`` as ``model=input,output;model2=...`` in dollars per million tokens
(without a price no cost is reported and ``--max-money`` is refused).
The runbook has the exact commands and the cost estimate. Not run by any test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from openai_agents_adapter import DEFAULT_MAX_TURNS, OpenAIAgentsAdapter
from sdk import OneShotUser, UserSimulator, converse, write_conversation, write_transcript

UNANSWERED_STOP_EXIT_CODE = 3
"""The run is reported as one that did not complete: the user left the agent's question open."""


def prices() -> dict[str, tuple[float, float]]:
    out = {}
    for item in filter(None, os.environ.get("ISITRIGHT_PRICES", "").split(";")):
        name, _, pair = item.partition("=")
        low, _, high = pair.partition(",")
        out[name] = (float(low), float(high))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-id", help="a tau2 task id; without it the task text is the only message"
    )
    parser.add_argument("--domain", default="airline")
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument(
        "--accept-unanswered-stop",
        action="store_true",
        help="count a conversation the user ended right after the agent's question as a completed "
        "run (by default it is a run that did not complete)",
    )
    args = parser.parse_args()
    agent_model = os.environ["ISITRIGHT_AGENT_MODEL"]
    run_dir = Path(os.environ["ISITRIGHT_RUN_DIR"])
    user: UserSimulator
    if args.task_id:
        from tau2.registry import registry  # tau2 is the owner's to install
        from tau2_bridge import Tau2UserBridge

        task = next(
            t for t in registry.get_tasks_loader(args.domain)() if str(t.id) == args.task_id
        )
        user = Tau2UserBridge(task, os.environ["ISITRIGHT_USER_MODEL"])
        policy = args.policy_file.read_text(encoding="utf-8") if args.policy_file else ""
    else:
        task_text = Path(os.environ["ISITRIGHT_TASK_FILE"]).read_text(encoding="utf-8")
        user, policy = OneShotUser(task_text), ""
    max_turns = int(os.environ.get("ISITRIGHT_AGENT_MAX_TURNS", DEFAULT_MAX_TURNS))
    agent = OpenAIAgentsAdapter(
        Path(os.environ["ISITRIGHT_MCP_CONFIG"]), policy, agent_model, max_turns
    )
    try:
        conversation = converse(agent, user)
    finally:
        agent.close()
    versions: dict[str, str] = {}
    try:
        import importlib.metadata as metadata

        versions = {"openai-agents": metadata.version("openai-agents")}
    except Exception:  # the version is a note, not a requirement
        pass
    write_conversation(run_dir, conversation)
    write_transcript(
        run_dir,
        provider="openai",
        model=agent_model,
        conversation=conversation,
        prices_per_million=prices(),
        sdk_versions=versions,
        settings={
            **json.loads(os.environ.get("ISITRIGHT_AGENT_SETTINGS", "{}")),
            "max_turns": max_turns,
        },
    )
    if conversation.stop_reason == "user_stop_unanswered" and not args.accept_unanswered_stop:
        sys.exit(UNANSWERED_STOP_EXIT_CODE)


if __name__ == "__main__":
    main()
