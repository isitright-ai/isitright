# Proposed fixture: pending owner review
"""Scenario over the Memory reference MCP server (a knowledge graph in a JSON-lines file).

The server is `@modelcontextprotocol/server-memory`, written and maintained by others. isitright
does not simulate it: it seeds a copy of the server's JSON-lines file from each world, starts the
real server on that copy, forwards the agent's calls and reads the file back after every call.

Setup (no account, no key; needs Node 24 or newer):

    npm install --prefix .tools/third-party @modelcontextprotocol/server-memory
    set ISITRIGHT_MEMORY_SERVER to dist/index.js of that package under <folder>/node_modules
    (the default path assumes the folder is .tools/third-party under the repository)

Written by the same author as the host and the scripted agents, so this shows that the host,
generator and oracle run on a server isitright did not write, not that the oracle is independent.
The entity schema, hints and oracle are drawn from the task text and the server's tool schemas.
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec, RefSpec
from isitright.core.hints import Hint, Hints
from isitright.core.hosts import Fidelity
from isitright.core.spec import ToolSpec, WorldSpec
from isitright.core.world import State
from isitright.packs.mcp.external import ExternalServer, JsonLinesFile
from isitright.packs.mcp.model import Invariant, Layout, McpScenario, ScenarioOracle, ToolDef

NAME = "Alice Chen"
OLD, NEW = "works at Acme Corp", "works at Beta Corp"
TASK = (
    f"{NAME} has changed employer. Record in the memory graph that she now {NEW} (as an "
    f"observation; do not create an entity for the new employer), and remove the fact that she "
    f"{OLD}: the observation, and her works_at relation to the old employer if the graph has one. "
    "Keep everything else the graph says about her, and do not change anything about anyone else."
)

SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="entities",
            key="name",
            fields=[
                FieldSpec(name="name"),
                FieldSpec(name="entityType"),
                FieldSpec(
                    name="observations",
                    type="json",
                    shape={"type": "array", "items": {"type": "string"}},
                ),
            ],
        ),
        CollectionSpec(
            name="relations",
            key="id",
            fields=[
                FieldSpec(name="id"),
                FieldSpec(name="from"),
                FieldSpec(name="to"),
                FieldSpec(name="relationType"),
            ],
            references=[
                RefSpec(field="from", to="entities", owned=True),
                RefSpec(field="to", to="entities", owned=True),
            ],
        ),
    ]
)
LAYOUT = Layout(keyed=("entities",), listed=("relations",), scalars=(), block="meta")


def _relation(source: str, target: str, kind: str) -> dict[str, str]:
    return {"id": f"{kind}|{source}|{target}", "from": source, "to": target, "relationType": kind}


BASE = State(
    {
        "entities": (
            {"name": NAME, "entityType": "person", "observations": [OLD, "prefers email"]},
            {"name": "Bob Stone", "entityType": "person", "observations": [OLD]},
            {"name": "Acme Corp", "entityType": "organization", "observations": []},
        ),
        "relations": (
            _relation(NAME, "Acme Corp", "works_at"),
            _relation("Bob Stone", "Acme Corp", "works_at"),
        ),
    },
    {"entities": "name", "relations": "id"},
)

TOOL_NAMES = (
    ("create_entities", True),
    ("create_relations", True),
    ("add_observations", True),
    ("delete_entities", True),
    ("delete_observations", True),
    ("delete_relations", True),
    ("read_graph", False),
    ("search_nodes", False),
    ("open_nodes", False),
)
GRAPH_FIELDS = ["entities.name", "entities.entityType", "entities.observations"]


def _no_handler(state: dict[str, Any], arguments: dict[str, Any]) -> Any:
    raise RuntimeError("this tool is served by the external server")


def _reference(call: Any) -> None:
    """What a careful agent does: read her entity, replace the old fact, add the new one once.

    The old fact is both the observation and her works_at relation to the old employer.
    """
    graph = call("read_graph")  # search_nodes drops a relation whose other end does not match
    people = [e for e in graph.get("entities", []) if e["name"] == NAME]
    if not people:
        entity = {"name": NAME, "entityType": "person", "observations": [NEW]}
        call("create_entities", entities=[entity])
        return
    old_employer = OLD.removeprefix("works at ")
    stale = [
        r
        for r in graph.get("relations", [])
        if r["from"] == NAME and r["to"] == old_employer and r["relationType"] == "works_at"
    ]
    if stale:
        call("delete_relations", relations=stale)
    seen = people[0]["observations"]
    if OLD in seen:
        call("delete_observations", deletions=[{"entityName": NAME, "observations": [OLD]}])
    if NEW not in seen:
        call("add_observations", observations=[{"entityName": NAME, "contents": [NEW]}])


def _normalize(state: dict[str, Any]) -> Any:
    return {
        "entities": {n: sorted(e["observations"]) for n, e in sorted(state["entities"].items())},
        "relations": sorted((r["from"], r["to"], r["relationType"]) for r in state["relations"]),
    }


def _only_alice_changes(before: dict[str, Any], after: dict[str, Any], trace: Any) -> list[str]:
    out = []
    for name, entity in before["entities"].items():
        if name == NAME:
            continue
        other = after["entities"].get(name)
        if other is None:
            out.append(f"{name} was deleted")
        elif sorted(other["observations"]) != sorted(entity["observations"]):
            out.append(f"the facts about {name} changed")
    return out


def _nothing_else_added(before: dict[str, Any], after: dict[str, Any], trace: Any) -> list[str]:
    added = sorted(set(after["entities"]) - set(before["entities"]))
    return [f"an entity was created that the task did not ask for: {n}" for n in added if n != NAME]


ORACLE = ScenarioOracle(
    name="memory_reference_procedure",
    invariants=[
        Invariant(
            "only_alice_changes", "the facts about everyone else are unchanged", _only_alice_changes
        ),
        Invariant(
            "no_other_entity_created",
            "no entity other than Alice Chen is created",
            _nothing_else_added,
        ),
    ],
    reference=_reference,
    normalize=_normalize,
    normalize_call=lambda tool, args: (tool, args),
    description="the graph left equals the one the reference procedure leaves",
)


def server_path() -> str:
    return os.environ.get(
        "ISITRIGHT_MEMORY_SERVER",
        ".tools/third-party/node_modules/@modelcontextprotocol/server-memory/dist/index.js",
    )


def available() -> bool:
    return shutil.which("node") is not None and os.path.isfile(server_path())


SERVER = ExternalServer(
    command=shutil.which("node") or "node",
    args=[server_path()],
    adapter=JsonLinesFile(
        "memory.jsonl",
        "MEMORY_FILE_PATH",
        {"entities": "entity", "relations": "relation"},
        keyed=("entities",),
    ),
)

SCENARIO = McpScenario(
    id="memory-employer-change",
    task=TASK,
    spec=WorldSpec(
        id="memory",
        schema=SCHEMA,
        tools=[
            ToolSpec(name=n, writes=w, exposes=[] if w else GRAPH_FIELDS) for n, w in TOOL_NAMES
        ],
        policy=TASK,
    ),
    tools=[ToolDef(n, n, {}, _no_handler, writes=w) for n, w in TOOL_NAMES],
    base=BASE,
    layout=LAYOUT,
    oracle=ORACLE,
    hints=Hints(
        [Hint(kind="lookup", args={"collection": "entities", "fields": ["name"], "value": [NAME]})]
    ),
    fidelity=Fidelity.NATIVE_ISOLATED,
    external=SERVER,
)
