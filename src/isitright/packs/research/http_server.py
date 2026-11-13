"""Serve the corpus tools over streamable-HTTP MCP, with a bearer token, for hosted agents.

Some hosted deep-research APIs reach tools only through a remote MCP server and expect the tools
`search` and `fetch`. This serves the same two tools as the stdio server (`serve.py`) from the same
``ToolHost``: the same refusals, the same frozen index, the same response edits, the same
``trace.jsonl``. ``fetch`` is `open` under another name: the trace records ``open``.

    python -m isitright.packs.research.http_server --world-file W.json --stats-file S.json \
        --run-dir DIR [--host 127.0.0.1] [--port 8765]

It binds to 127.0.0.1 by default and requires ``Authorization: Bearer <token>``; the token is
generated at start (``secrets.token_urlsafe(32)``) and printed once on stderr with the URL, or taken
from the environment variable named by ``--token-env``. A request without it gets 401 and reaches
nothing. Needs the ``mcp`` extra (which brings uvicorn and starlette).

**Exposure.** A hosted API cannot reach 127.0.0.1: it needs a URL on the public internet (a
tunnel or a host you control). Anyone with that URL and the token can call the two tools, and the
tools return the corpus text of this world. The token is the only protection; nothing here limits
request rate. Run it for the length of one run and stop it. A non-loopback ``--host`` needs
``--allow-public-bind``. The server is not set up for you.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import secrets
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from isitright.packs.research.retrieval import ToolHost
from isitright.packs.research.serve import TOOL_SCHEMAS, build_host

ALIASES = {"fetch": "open"}
"""Name offered to the agent -> the host's tool."""

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def http_tool_schemas() -> dict[str, dict[str, Any]]:
    """The tools as listed over HTTP: `search` and `fetch` (`open`'s schema under its alias)."""
    out = {"search": TOOL_SCHEMAS["search"]}
    for alias, name in ALIASES.items():
        spec = dict(TOOL_SCHEMAS[name])
        spec["description"] = "Return one document of the corpus by id: title, source, date, text."
        out[alias] = spec
    return out


def build_app(host: ToolHost, run_dir: Path, token: str) -> Any:
    """An ASGI app: the MCP endpoint at ``/mcp`` behind the bearer check."""
    from mcp.server.streamable_http_manager import (
        StreamableHTTPASGIApp,
        StreamableHTTPSessionManager,
    )
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from isitright.packs.mcp.host import HostTool, build_server
    from isitright.packs.mcp.trace import TraceEvent, TraceRecorder

    schemas = http_tool_schemas()
    tools = [HostTool(n, s["description"], s["input_schema"]) for n, s in schemas.items()]
    trace_path = run_dir / "trace.jsonl"

    def persist(event: TraceEvent) -> None:
        record = dict(event.__dict__)
        record["name"] = ALIASES.get(str(record["name"]), record["name"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def handler(name: str, arguments: dict[str, Any]) -> str:
        return host.call(ALIASES.get(name, name), arguments)

    server = build_server("isitright-research", tools, handler, TraceRecorder(on_record=persist))
    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True)
    expected = f"Bearer {token}".encode()

    @contextlib.asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        async with manager.run():
            yield

    inner = Starlette(routes=[Mount("/mcp", app=StreamableHTTPASGIApp(manager))], lifespan=lifespan)

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, expected):
                seen = 0  # read (and drop) a bounded part of the body, so the client sees the 401
                while seen < 1 << 20:
                    message = await receive()
                    seen += len(message.get("body", b""))
                    if not message.get("more_body"):
                        break
                body = b'{"error": "a bearer token is required"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await inner(scope, receive, send)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m isitright.packs.research.http_server")
    parser.add_argument("--world-file", required=True, type=Path)
    parser.add_argument("--stats-file", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-env", help="read the token from this environment variable")
    parser.add_argument("--allow-public-bind", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK and not args.allow_public_bind:
        print(
            f"refusing to bind {args.host}: pass --allow-public-bind (see the module docstring)",
            file=sys.stderr,
        )
        return 2
    token = os.environ.get(args.token_env, "") if args.token_env else secrets.token_urlsafe(32)
    if not token:
        print(f"{args.token_env} is not set", file=sys.stderr)
        return 2
    try:
        host = build_host(args.world_file, args.stats_file)
    except (OSError, ValueError, KeyError) as error:
        print(f"cannot load the world: {error}", file=sys.stderr)
        return 2
    args.run_dir.mkdir(parents=True, exist_ok=True)
    import uvicorn

    print(f"serving http://{args.host}:{args.port}/mcp", file=sys.stderr)
    if not args.token_env:
        print(f"bearer token: {token}", file=sys.stderr)
    uvicorn.run(
        build_app(host, args.run_dir, token),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
