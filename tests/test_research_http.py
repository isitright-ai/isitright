"""The corpus tools over streamable-HTTP MCP: a real local connection, the bearer token, `search`
and `fetch`, the same refusals and the same trace as the stdio server.

Proposed fixture: pending owner review (the expected tool results are the 0.8 corpus's).
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")
pytest.importorskip("uvicorn")

import uvicorn

from isitright.core.mutations import World
from isitright.packs.research import http_server
from isitright.packs.research.documents import COLLECTION
from isitright.packs.research.retrieval import FrozenStats
from isitright.packs.research.serve import build_host

from .research_fixtures import corpus

TOKEN = "test-token-not-secret"


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    stats = FrozenStats.from_documents(corpus().entities(COLLECTION))
    (tmp_path / "world.json").write_text(json.dumps(World(corpus()).to_json()), encoding="utf-8")
    (tmp_path / "stats.json").write_text(json.dumps(stats.to_json()), encoding="utf-8")
    host = build_host(tmp_path / "world.json", tmp_path / "stats.json")
    app = http_server.build_app(host, tmp_path, TOKEN)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not instance.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert instance.started, "the server did not start"
    try:
        yield f"http://127.0.0.1:{port}/mcp", tmp_path
    finally:
        instance.should_exit = True
        thread.join(timeout=10)


async def _session(url: str, token: str, work: Any) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with (
        client,
        streamable_http_client(url, http_client=client) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await work(session)


def run(url: str, work: Any, token: str = TOKEN) -> Any:
    return asyncio.run(asyncio.wait_for(_session(url, token, work), timeout=60))


def test_a_request_without_the_token_is_refused_before_reaching_a_tool(
    server: tuple[str, Path],
) -> None:
    url, run_dir = server
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
        request = urllib.request.Request(
            url, data=b"{}", headers={"Content-Type": "application/json", **headers}
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=10)
        assert refused.value.code == 401
        assert refused.value.headers["WWW-Authenticate"] == "Bearer"
    assert not (run_dir / "trace.jsonl").exists()


def test_the_tools_are_search_and_fetch_and_serve_the_same_corpus(
    server: tuple[str, Path],
) -> None:
    url, run_dir = server

    async def work(session: Any) -> tuple[list[str], str, str]:
        listed = sorted(t.name for t in (await session.list_tools()).tools)
        found = await session.call_tool("search", {"query": "Halvorsen Bridge completed", "k": 2})
        top = json.loads(found.content[0].text)["results"][0]["id"]
        opened = await session.call_tool("fetch", {"id": top})
        return listed, top, opened.content[0].text

    listed, top, text = run(url, work)
    assert listed == ["fetch", "search"]
    assert top.startswith("bridge-halvorsen") and "Halvorsen" in text
    # the trace is the stdio server's: the host's names (open, not fetch), one event per call
    events = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
    assert [e["name"] for e in events] == ["search", "open"]
    assert events[1]["arguments"] == {"id": top} and not events[1]["is_error"]


def test_the_refusals_are_the_hosts(server: tuple[str, Path]) -> None:
    url, run_dir = server

    async def work(session: Any) -> list[tuple[bool, str]]:
        out = []
        for name, args in (
            ("open", {"id": "bridge-halvorsen-1962"}),  # the host's own name is not offered
            ("fetch", {"id": "../../etc/passwd"}),
            ("fetch", {"id": "x", "extra": 1}),
            ("search", {"query": "x", "k": 99}),
        ):
            result = await session.call_tool(name, args)
            out.append((bool(result.is_error), result.content[0].text))
        return out

    refused = run(url, work)
    assert all(error for error, _ in refused), refused
    assert "no document with id" in refused[1][1]
    events = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
    # every refused call reached the host and was traced as an error, in the order it was made
    assert [(e["name"], e["arguments"], e["is_error"]) for e in events] == [
        ("open", {"id": "bridge-halvorsen-1962"}, True),
        ("open", {"id": "../../etc/passwd"}, True),
        ("open", {"id": "x", "extra": 1}, True),
        ("search", {"query": "x", "k": 99}, True),
    ]


def test_it_binds_to_loopback_unless_told_otherwise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--world-file", "w", "--stats-file", "s", "--run-dir", str(tmp_path)]
    assert http_server.main([*args, "--host", "0.0.0.0"]) == 2
    assert "--allow-public-bind" in capsys.readouterr().err
    assert http_server.main([*args, "--token-env", "ISITRIGHT_NO_SUCH_TOKEN"]) == 2
    assert "ISITRIGHT_NO_SUCH_TOKEN is not set" in capsys.readouterr().err
