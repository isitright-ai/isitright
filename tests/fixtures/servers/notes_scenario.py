"""A scenario over the notes server: the world is its SQLite database, the oracle is ours.

Task: delete every note that mentions "draft" and keep the others. Written by the same author as
the host, so the case shows the machinery works, not that the oracle is independent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.hints import Hint, Hints
from isitright.core.hosts import Fidelity
from isitright.core.spec import ToolSpec, WorldSpec
from isitright.core.world import State
from isitright.packs.mcp.external import ExternalServer, SqliteFile
from isitright.packs.mcp.model import Invariant, Layout, McpScenario, ScenarioOracle, ToolDef

HERE = Path(__file__).parent
TASK = 'Delete every note that mentions "draft" (any capitalization) and keep all the others.'

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="notes",
            key="id",
            fields=[FieldSpec(name="id", type="int"), FieldSpec(name="text")],
        )
    ]
)
LAYOUT = Layout(keyed=(), listed=("notes",), scalars=(), block="meta")
BASE = State(
    {
        "notes": (
            {"id": 1, "text": "buy milk"},
            {"id": 2, "text": "Draft of the report"},
            {"id": 3, "text": "call Sam"},
        )
    },
    {"notes": "id"},
)


def _no_handler(state: dict[str, Any], arguments: dict[str, Any]) -> Any:
    raise RuntimeError("this tool is served by the external server")


def _reference(call: Any) -> None:
    for note in call("list_notes")["notes"]:
        if "draft" in note["text"].lower():
            call("delete_note", note_id=note["id"])


def _kept(state: dict[str, Any]) -> Any:
    return sorted(n["text"] for n in state["notes"])


def _only_drafts_go(before: dict[str, Any], after: dict[str, Any], trace: Any) -> list[str]:
    kept = [n["text"] for n in before["notes"] if "draft" not in n["text"].lower()]
    gone = [t for t in kept if t not in [n["text"] for n in after["notes"]]]
    return [f"a note that is not a draft was deleted: {t!r}" for t in gone]


ORACLE = ScenarioOracle(
    name="notes_reference_procedure",
    invariants=[
        Invariant(
            "only_drafts_are_deleted", "a note without 'draft' is never deleted", _only_drafts_go
        )
    ],
    reference=_reference,
    normalize=_kept,
    normalize_call=lambda tool, args: (tool, {}),
    description="the notes left equal those the reference procedure leaves",
)

SERVER = ExternalServer(
    command=sys.executable,
    args=[str(HERE / "notes_server.py")],
    adapter=SqliteFile(
        "notes.sqlite",
        {"notes": "CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL)"},
        env_var="NOTES_DB",
    ),
)

SCENARIO = McpScenario(
    id="notes-drafts",
    task=TASK,
    spec=WorldSpec(
        id="notes",
        schema=SCHEMA,
        tools=[
            ToolSpec(name="list_notes", exposes=["notes.id", "notes.text"]),
            ToolSpec(name="add_note", writes=True),
            ToolSpec(name="delete_note", writes=True),
        ],
        policy=TASK,
    ),
    tools=[
        ToolDef("list_notes", "List every note.", {}, _no_handler),
        ToolDef("add_note", "Add a note.", {}, _no_handler, writes=True),
        ToolDef("delete_note", "Delete a note by id.", {}, _no_handler, writes=True),
    ],
    base=BASE,
    layout=LAYOUT,
    oracle=ORACLE,
    hints=Hints(
        [Hint(kind="threshold", name="notes_seen", args={"collection": "notes", "count": 3})]
    ),
    fidelity=Fidelity.NATIVE_ISOLATED,
    external=SERVER,
)
