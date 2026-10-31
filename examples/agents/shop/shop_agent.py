# Provenance
# Author:   an OpenAI model, via the owner as conduit (exact model name: owner to confirm).
# Brief:    2026-10-28-brief-B-agent-loop.md. Returned with requirements.txt and a readme.
# Received: 2026-10-28.
# Reviewed: read in full by Claude (Sonnet 5.5) on 2026-10-28 before it was run.
# Changes:  one line, in check_mcp(): the f-string held a backslash inside its expression, which
#           is a SyntaxError on Python 3.11 (the brief's target). The newline escape is now
#           computed outside the f-string. Nothing else differs from the returned file.

"""A small, transparent MCP tool-calling agent for Anthropic and OpenAI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from importlib.metadata import version
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the provided tools to complete the user's request."
)


def read_utf8(path: str) -> str:
    """Read UTF-8 without changing line endings."""
    return Path(path).read_bytes().decode("utf-8")


def server_params() -> StdioServerParameters:
    """Read the MCP config and return its exact stdio launch parameters."""
    config = json.loads(read_utf8(os.environ["ISITRIGHT_MCP_CONFIG"]))
    return StdioServerParameters(**config["mcpServers"]["isitright"])


async def list_all_tools(client: Client) -> list[Any]:
    """Follow MCP pagination until every tool has been listed."""
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor) if cursor else await client.list_tools()
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return tools


def tool_result_text(result: Any) -> str:
    """Preserve text blocks and serialize all other returned content."""
    parts = [
        block.text
        if block.type == "text"
        else json.dumps(block.model_dump(exclude_none=True), ensure_ascii=False)
        for block in result.content
    ]
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    return "\n".join(parts)


async def run_tool_calls(client: Client, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Call each requested MCP tool in order; preserve errors and responses."""
    results = []
    for call in calls:
        outcome = await client.call_tool(call["name"], call["arguments"])
        results.append(
            {
                "id": call["id"],
                "text": tool_result_text(outcome),
                "is_error": bool(outcome.is_error),
            }
        )
    return results


async def run_anthropic(client: Client, tools: list[Any], record: dict[str, Any]) -> None:
    """Use the Anthropic SDK directly, once per model turn."""
    import anthropic

    sdk = anthropic.Anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": record["messages"][0]["text"]}]
    definitions = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
    settings = record["settings"]
    for _ in range(settings["max_turns"]):
        params: dict[str, Any] = {
            "model": record["model"],
            "system": record["system_prompt"],
            "messages": messages,
            "max_tokens": settings["max_output_tokens"],
        }
        if definitions:
            params["tools"] = definitions
        if settings["temperature"] is not None:
            params["temperature"] = settings["temperature"]
        response = sdk.messages.create(**params)
        record["usage"].append(
            {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        )
        calls = [
            {"id": b.id, "name": b.name, "arguments": b.input}
            for b in response.content
            if b.type == "tool_use"
        ]
        answer = "".join(b.text for b in response.content if b.type == "text")
        record["messages"].append({"role": "assistant", "text": answer, "tool_calls": calls})
        if not calls:
            record["stop_reason"], record["final_text"] = "final", answer
            return
        messages.append(
            {
                "role": "assistant",
                "content": [b.model_dump(exclude_none=True) for b in response.content],
            }
        )
        results = await run_tool_calls(client, calls)
        record["messages"].append({"role": "tool", "results": results})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],
                        "content": r["text"],
                        "is_error": r["is_error"],
                    }
                    for r in results
                ],
            }
        )
    record["stop_reason"] = "max_turns"


async def run_openai(client: Client, tools: list[Any], record: dict[str, Any]) -> None:
    """Use OpenAI Chat Completions directly, once per model turn."""
    import openai

    sdk = openai.OpenAI()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": record["system_prompt"]},
        {"role": "user", "content": record["messages"][0]["text"]},
    ]
    definitions = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]
    settings = record["settings"]
    for _ in range(settings["max_turns"]):
        params: dict[str, Any] = {
            "model": record["model"],
            "messages": messages,
            "max_completion_tokens": settings["max_output_tokens"],
        }
        if definitions:
            params["tools"] = definitions
        if settings["temperature"] is not None:
            params["temperature"] = settings["temperature"]
        response = sdk.chat.completions.create(**params)
        usage = response.usage
        record["usage"].append(
            {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
            }
        )
        message = response.choices[0].message
        raw_calls = message.tool_calls or []
        calls = [
            {"id": c.id, "name": c.function.name, "arguments": json.loads(c.function.arguments)}
            for c in raw_calls
        ]
        answer = message.content or ""
        record["messages"].append({"role": "assistant", "text": answer, "tool_calls": calls})
        if not calls:
            record["stop_reason"], record["final_text"] = "final", answer
            return
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": c.type,
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in raw_calls
                ],
            }
        )
        results = await run_tool_calls(client, calls)
        record["messages"].append({"role": "tool", "results": results})
        for result in results:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result["id"],
                    "content": result["text"],
                }
            )
    record["stop_reason"] = "max_turns"


async def check_mcp() -> None:
    """List tools without reading task, provider, or API-key settings."""
    async with Client(server_params(), mode="legacy") as client:
        for tool in await list_all_tools(client):
            description = (tool.description or "").replace(chr(10), chr(92) + "n")
            print(f"{tool.name}: {description}")


async def run_agent() -> int:
    """Run the model and always attempt to write a transcript."""
    record: dict[str, Any] = {
        "provider": "",
        "model": "",
        "sdk_versions": {},
        "system_prompt": "",
        "settings": {"max_turns": 20, "max_output_tokens": 2048, "temperature": None},
        "messages": [],
        "tools": [],
        "usage": [],
        "stop_reason": "error",
        "final_text": "",
        "error": None,
    }
    run_dir: Path | None = None
    try:
        run_dir = Path(os.environ["ISITRIGHT_RUN_DIR"])
        record["provider"] = os.environ["AGENT_PROVIDER"]
        record["model"] = os.environ["AGENT_MODEL"]
        record["sdk_versions"] = {name: version(name) for name in ("mcp", "anthropic", "openai")}
        settings = record["settings"]
        settings["max_turns"] = int(os.environ.get("AGENT_MAX_TURNS", "20"))
        settings["max_output_tokens"] = int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "2048"))
        temperature = os.environ.get("AGENT_TEMPERATURE")
        settings["temperature"] = float(temperature) if temperature is not None else None
        prompt_file = os.environ.get("AGENT_SYSTEM_PROMPT_FILE")
        record["system_prompt"] = (
            read_utf8(prompt_file) if prompt_file is not None else DEFAULT_SYSTEM_PROMPT
        )
        record["messages"].append(
            {
                "role": "user",
                "text": read_utf8(os.environ["ISITRIGHT_TASK_FILE"]),
            }
        )
        async with Client(server_params(), mode="legacy") as client:
            tools = await list_all_tools(client)
            record["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
            if record["provider"] == "anthropic":
                await run_anthropic(client, tools, record)
            elif record["provider"] == "openai":
                await run_openai(client, tools, record)
            else:
                raise ValueError(f"Unsupported provider: {record['provider']}")
    except Exception as exc:
        record["stop_reason"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "transcript.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    return {"final": 0, "max_turns": 2, "error": 1}[record["stop_reason"]]


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-mcp"]:
        try:
            asyncio.run(check_mcp())
        except Exception:
            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)
    sys.exit(asyncio.run(run_agent()))
