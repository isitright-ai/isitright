"""String and list-element edits in the JSON family (0.9): only where a json_path hint names text.

Proposed fixture: pending owner review (the toy schema, the declared values and the Memory
expectation are written by Claude, who also wrote the family and the Memory scenario).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.families.json import JsonEdit
from isitright.core.hints import Hint, Hints
from isitright.core.mutations import World, apply_edits
from isitright.core.spec import WorldSpec
from isitright.core.world import State

SHAPE = {"type": "array", "items": {"type": "string"}}
SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="people",
            key="name",
            fields=[FieldSpec(name="name"), FieldSpec(name="facts", type="json", shape=SHAPE)],
        )
    ]
)
BASE = State({"people": ({"name": "ann", "facts": ["works at Acme"]},)}, {"people": "name"})
HINT = Hint(
    kind="json_path",
    name="facts",
    args={"path": "people.facts[*]", "values": ["works at Beta", "works at Acme"]},
)


def proposals(hints: Hints) -> dict[str, Any]:
    spec = WorldSpec(id="w", schema=SCHEMA)
    out = {}
    for mutation in JsonEdit().propose(spec, World(BASE), hints):
        state = apply_edits(BASE, mutation.edits)
        out[mutation.description] = next(iter(state.entities("people")))["facts"]
    return out


def test_a_hinted_list_of_text_gets_declared_values_inserted_and_its_text_edited() -> None:
    got = proposals(Hints([HINT]))
    added = {k: v for k, v in got.items() if "added" in k}
    assert ["works at Acme", "works at Beta"] in added.values()  # the new fact already there
    assert ["works at Beta", "works at Acme"] in added.values()  # ... at the start
    assert not any(v.count("works at Acme") > 1 for v in added.values())  # present: not added
    values = list(got.values())
    assert ["works at Beta"] in values  # the old fact replaced by the new one
    assert ["WORKS AT ACME"] in values and ["works at Acme "] in values and [""] in values
    assert [] in values  # the element removed (the 0.5 list edits still apply)


def test_without_a_text_hint_a_shape_alone_edits_no_text() -> None:
    """A shape scopes numeric leaves only, as in 0.5: an array of text gets nothing."""
    assert proposals(Hints([])) == {}


def test_a_hint_without_values_edits_the_text_but_inserts_nothing() -> None:
    bare = Hint(kind="json_path", name="facts", args={"path": "people.facts[*]"})
    got = proposals(Hints([bare]))
    assert got and not any("added" in k for k in got)
    assert ["WORKS AT ACME"] in got.values()


def test_the_memory_graph_gets_the_world_where_the_new_fact_is_already_there() -> None:
    """The 0.5 gap: the generic families could not build it on the Memory server's graph."""
    from isitright.packs.mcp.model import load_scenario

    path = Path(__file__).parents[1] / "examples" / "agents" / "memory" / "scenario.py"
    built = load_scenario(f"{path}:SCENARIO")
    new, old = "works at Beta Corp", "works at Acme Corp"  # the task's two facts
    found = []
    for mutation in JsonEdit().propose(built.spec, World(built.base), built.hints):
        state = apply_edits(built.base, mutation.edits)
        alice = next(e for e in state.entities("entities") if e["name"] == "Alice Chen")
        found.append(alice["observations"])
    assert [old, "prefers email", new] in found
    assert [new, "prefers email"] in found  # the old fact already replaced
