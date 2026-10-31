"""Example hint proposer: shows where a real model client plugs in. No key is stored or needed here.

`ModelHintProposer` builds a prompt from the task text, the policy text, the tool schemas and the
entity model, hands it to ``complete`` (any function from a prompt to the model's text), and parses
the JSON array it returns into hints. Tests pass a function that returns a recorded response, so
they need no key and no network. For a real run, ``default_complete`` shows the one place a client
goes: it reads the key from the environment when it is called, never at import and never stored.

    isitright agents hints propose --trust-code ^
        --scenario examples/agents/shop/scenario.py:SCENARIO ^
        --proposer examples/proposers/model_proposer.py:PROPOSER --output hints.yaml

Every hint it returns is labeled `proposed` by isitright. A proposed hint prioritizes the search
and never grants a validity tier. Confirm the ones you agree with:

    isitright agents hints confirm hints.yaml --accept lookup_by_name
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

from isitright.core.hints import Hint
from isitright.core.proposals import ProposalRequest

VOCABULARY = """\
Hint kinds (arguments name collections and fields of the entity model; paths are dotted):
- lookup:   {collection, fields: [..], value: [..]}       how the task finds an entity
- ordering: {collection, field, direction: asc|desc}      "most recent", "cheapest"
- gate:     {collection, field, allows: [..], action}     a status that allows a tool action
- scope:    {collection, where}                           the entities the right answer depends on
- threshold:{path, value} or {collection, count, where}   a numeric or time cut-off
- json_path:{path: "orders.items[*].price", same_as: [..]} a path inside a JSON field
"""


def build_prompt(request: ProposalRequest) -> str:
    """The text sent to the model. Pure: no key, no network."""
    tools = "\n".join(
        f"- {t.name}{' (writes)' if t.writes else ''}: {t.description} "
        f"input={json.dumps(t.input_schema, sort_keys=True)}"
        for t in request.tools
    )
    collections = "\n".join(
        f"- {c.name} (key {c.key}): " + ", ".join(f.name for f in c.fields)
        for c in request.schema.collections
    )
    return (
        "You help audit a tool-using agent. From the task, the policy and the tool schemas, "
        "propose hints that tell a world generator which entities and fields matter.\n\n"
        f"TASK:\n{request.task}\n\nPOLICY:\n{request.policy or '(in the task)'}\n\n"
        f"TOOLS:\n{tools}\n\nENTITY MODEL:\n{collections}\n\n{VOCABULARY}\n"
        'Answer with a JSON array of {"name": "...", "kind": "...", "args": {...}, '
        '"note": "why"} and nothing else. Use only collections and fields listed above.'
    )


def parse_response(text: str) -> list[Hint]:
    """Hints from the model's text: a JSON array, possibly inside a code fence."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    body = fenced.group(1) if fenced else text
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        items: list[dict[str, Any]] = json.loads(body[start : end + 1])
    except ValueError:
        return []
    hints = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("kind"), str):
            hints.append(
                Hint(
                    kind=item["kind"],
                    name=str(item.get("name") or ""),
                    args=dict(item.get("args") or {}),
                )
            )
    return hints


def default_complete(prompt: str) -> str:  # pragma: no cover - needs a key and a network
    """Where a real model client goes. The key comes from the environment at call time."""
    key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("ISITRIGHT_HINT_MODEL")
    if not key or not model:
        raise RuntimeError(
            "set OPENAI_API_KEY and ISITRIGHT_HINT_MODEL (a model name), or pass your own "
            "`complete` function to ModelHintProposer"
        )
    from openai import OpenAI  # installed by the owner; not an isitright dependency

    reply = OpenAI(api_key=key).chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}]
    )
    return reply.choices[0].message.content or ""


class ModelHintProposer:
    def __init__(self, complete: Callable[[str], str] | None = None) -> None:
        self.complete = complete or default_complete

    def propose(self, request: ProposalRequest) -> list[Hint]:
        return parse_response(self.complete(build_prompt(request)))


PROPOSER = ModelHintProposer()
