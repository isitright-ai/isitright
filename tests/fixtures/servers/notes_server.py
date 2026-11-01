"""A small MCP server whose state lives in a SQLite file: the in-repository stand-in for a
third-party server in the tests of the external-server host.

It knows nothing about isitright's scenarios. It reads its database path from ``NOTES_DB`` and
offers three tools: ``list_notes``, ``add_note`` and ``delete_note``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from typing import Any

from isitright.packs.mcp.host import HostTool, build_server, serve_stdio
from isitright.packs.mcp.trace import TraceRecorder

TOOLS = [
    HostTool("list_notes", "List every note.", {"type": "object", "properties": {}}),
    HostTool(
        "add_note",
        "Add a note.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    HostTool(
        "delete_note",
        "Delete a note by id.",
        {
            "type": "object",
            "properties": {"note_id": {"type": "integer"}},
            "required": ["note_id"],
        },
    ),
]


def handle(name: str, arguments: dict[str, Any]) -> str:
    with closing(sqlite3.connect(os.environ["NOTES_DB"])) as connection, connection:
        if name == "list_notes":
            rows = connection.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
            return json.dumps({"notes": [{"id": i, "text": t} for i, t in rows]})
        if name == "add_note":
            cursor = connection.execute("INSERT INTO notes (text) VALUES (?)", (arguments["text"],))
            return json.dumps({"id": cursor.lastrowid})
        if name == "delete_note":
            cursor = connection.execute("DELETE FROM notes WHERE id = ?", (arguments["note_id"],))
            if cursor.rowcount == 0:
                raise ValueError(f"no note {arguments['note_id']}")
            return "{}"
    raise ValueError(f"unknown tool {name}")


if __name__ == "__main__":
    serve_stdio(build_server("notes", TOOLS, handle, TraceRecorder()))
