"""Serve one world's corpus tools, `search` and `open`, as a stdio MCP server.

The agent's MCP client launches this module from the injected ``mcp.json``. One process is one
world: it loads the world file and the frozen index statistics, serves exactly two read-only tools,
applies the world's response edits and appends every call to ``trace.jsonl`` in the run directory.
stdout carries the protocol, so nothing else may print to it. Needs the ``mcp`` extra.

    python -m isitright.packs.research.serve --world-file W.json --stats-file S.json --run-dir DIR

Nothing here reaches the network or the file system beyond the two files it is given and the run
directory. The tools cannot be asked for anything but a ranked list and one document by id; a call
to any other tool name is an error result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from isitright.core.mutations import World
from isitright.packs.research.documents import COLLECTION
from isitright.packs.research.retrieval import FrozenStats, ToolError, ToolHost, build_index

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search": {
        "description": "Rank the corpus documents for a query. Returns ids, titles and snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "open": {
        "description": "Return one document of the corpus by id: title, source, date and text.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
}


def build_host(world_file: Path, stats_file: Path) -> ToolHost:
    world = World.from_json(json.loads(world_file.read_text(encoding="utf-8")))
    stats = FrozenStats.from_json(json.loads(stats_file.read_text(encoding="utf-8")))
    index = build_index(stats, list(world.state.entities(COLLECTION)))
    return ToolHost(index, world.response_edits)


def build_mcp_server(host: ToolHost, run_dir: Path) -> Any:
    from isitright.packs.research.mcp_bridge import make_server

    return make_server(host, run_dir, TOOL_SCHEMAS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m isitright.packs.research.serve")
    parser.add_argument("--world-file", required=True, type=Path)
    parser.add_argument("--stats-file", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        host = build_host(args.world_file, args.stats_file)
    except (OSError, ValueError, KeyError) as error:
        print(f"cannot load the world: {error}", file=sys.stderr)
        return 2
    args.run_dir.mkdir(parents=True, exist_ok=True)
    from isitright.packs.mcp.host import serve_stdio

    serve_stdio(build_mcp_server(host, args.run_dir))
    return 0


__all__ = ["TOOL_SCHEMAS", "ToolError", "build_host", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
