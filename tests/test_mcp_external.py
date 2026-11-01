"""A third-party server as the service: seed its storage, forward the agent's calls, read it back.

The in-repository fixture server keeps notes in SQLite (the state lives in a file the host can seed
and read). The scripted agents and the oracle are ours: this shows the host, generator and oracle
work on a server isitright's host did not write, not that the oracle is independent.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from isitright.core.mutations import World
from isitright.core.oracles import Role
from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.external import ExternalCaller, JsonLinesFile, SqliteFile
from isitright.packs.mcp.generate import generate_worlds
from isitright.packs.mcp.model import load_scenario
from isitright.packs.mcp.oracle import reference_outcome
from isitright.packs.mcp.replay import replay_report
from isitright.packs.mcp.session import McpSession

FIXTURES = Path(__file__).parent / "fixtures" / "servers"
REF = f"{FIXTURES / 'notes_scenario.py'}:SCENARIO"
AGENT = f'"{sys.executable}" "{FIXTURES / "notes_agent.py"}"'


def test_sqlite_state_is_seeded_and_read_back(tmp_path: Path) -> None:
    adapter = SqliteFile(
        "n.sqlite", {"notes": "CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)"}, "DB"
    )
    env = adapter.seed({"notes": [{"id": 7, "text": "a"}, {"id": 9, "text": "b"}]}, tmp_path)
    assert env == {"DB": str(tmp_path / "n.sqlite")}
    with closing(sqlite3.connect(tmp_path / "n.sqlite")) as connection, connection:
        connection.execute("INSERT INTO notes (text) VALUES ('c')")
    assert adapter.read(tmp_path) == {
        "notes": [{"id": 7, "text": "a"}, {"id": 9, "text": "b"}, {"id": 10, "text": "c"}]
    }
    adapter.seed({"notes": []}, tmp_path)  # seeding again starts from the given state
    assert adapter.read(tmp_path) == {"notes": []}


def test_json_lines_state_round_trips_and_keeps_unknown_lines_out(tmp_path: Path) -> None:
    adapter = JsonLinesFile(
        "g.jsonl",
        "GRAPH",
        {"entities": "entity", "relations": "relation"},
        keyed=("entities",),
    )
    service = {
        "entities": {"a": {"name": "a", "observations": ["x"]}},
        "relations": [{"id": "r1", "from": "a", "to": "b", "relationType": "knows"}],
    }
    adapter.seed(service, tmp_path)
    lines = [json.loads(line) for line in (tmp_path / "g.jsonl").read_text().splitlines()]
    assert {line["type"] for line in lines} == {"entity", "relation"}
    assert all("id" not in line for line in lines if line["type"] == "relation")
    with (tmp_path / "g.jsonl").open("a") as handle:
        handle.write('{"type": "other", "x": 1}\n\n')
    read = adapter.read(tmp_path)
    assert read["entities"] == service["entities"]
    assert [(r["from"], r["to"]) for r in read["relations"]] == [("a", "b")]
    assert JsonLinesFile("none.jsonl", "G", {"e": "entity"}).read(tmp_path) == {"e": []}


def test_the_reference_runs_against_the_real_server_and_roles_follow_the_world() -> None:
    scenario = load_scenario(REF)
    base = reference_outcome(scenario, World(scenario.base))
    assert base.role is Role.CONTROL and base.write_calls
    assert base.after is not None
    assert sorted(n["text"] for n in base.after["notes"]) == ["buy milk", "call Sam"]
    clean = World(
        scenario.base.evolve({"notes": [{"id": 1, "text": "buy milk"}, {"id": 2, "text": "call"}]})
    )
    assert reference_outcome(scenario, clean).role is Role.TRAP  # nothing to delete: do nothing


def test_the_proxy_forwards_calls_and_exports_state(tmp_path: Path) -> None:
    from mcp.client.stdio import StdioServerParameters

    scenario = load_scenario(REF)
    run_dir = tmp_path / "run"
    world_file = tmp_path / "world.json"
    world_file.write_text(json.dumps(World(scenario.base).to_json()), encoding="utf-8")
    session = McpSession(
        StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "isitright.packs.mcp.serve",
                "--scenario",
                REF,
                "--world-file",
                str(world_file),
                "--run-dir",
                str(run_dir),
                "--trust-code",
            ],
        )
    )
    try:
        assert {t.name for t in session.list_tools()} == {"list_notes", "add_note", "delete_note"}
        caller = ExternalCaller(session)
        assert len(caller("list_notes")["notes"]) == 3
        caller("delete_note", note_id=2)
        with pytest.raises(Exception, match="no note 99"):
            caller("delete_note", note_id=99)
    finally:
        session.close()
    before = json.loads((run_dir / "state_before.json").read_text(encoding="utf-8"))
    after = json.loads((run_dir / "state_after.json").read_text(encoding="utf-8"))
    assert len(before["notes"]) == 3 and [n["id"] for n in after["notes"]] == [1, 3]
    rows = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
    assert [r["name"] for r in rows] == ["list_notes", "delete_note", "delete_note"]
    assert rows[-1]["is_error"] is True


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[object, Path]]:
    out = {}
    for mode in ("reference", "careless", "refuse"):
        output = tmp_path_factory.mktemp(mode) / "out"
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("NOTES_AGENT_MODE", mode)
            report = run_scenario(
                scenario_ref=REF,
                agent_command=AGENT,
                output_dir=output,
                worlds="generated",
                k=1,
                attempts=40,
                max_worlds=8,
                sequential=False,
                trust_code=True,
                timeout_seconds=60,
            )
        out[mode] = (report, output)
    return out


def test_generated_worlds_run_against_the_external_server_and_agents_are_told_apart(
    runs: dict[str, tuple[object, Path]],
) -> None:
    findings = {m: len(r.cases[0].findings) for m, (r, _) in runs.items()}  # type: ignore[attr-defined]
    assert findings["reference"] == 0
    assert findings["careless"] >= 1  # the duplicated draft note is deleted once, not twice
    assert findings["refuse"] >= 1  # nothing deleted where the reference deletes
    case = runs["careless"][0].cases[0]  # type: ignore[attr-defined]
    assert case.execution_fidelity.found_on == "NATIVE_ISOLATED"
    assert any(w.role == "control" for w in case.worlds)
    assert all(
        w.screening and w.screening.screening_class == "UNSCREENABLE"
        for w in case.worlds
        if w.id != "baseline"
    )  # no in-process service to replay a trace on
    assert case.search.screening is not None
    baseline = next(r for r in case.extensions["mcp"]["runs"] if r["world_id"] == "baseline")
    assert baseline["outcome"] in ("MET", "NOT_MET") and baseline["run_status"] == "COMPLETED"


def test_a_report_on_an_external_server_replays_by_rejudging_the_recorded_run(
    runs: dict[str, tuple[object, Path]],
) -> None:
    report, output = runs["careless"]
    outcomes = replay_report(report, None, output)  # type: ignore[arg-type]
    assert outcomes and all(o.reproduced for o in outcomes), [
        o for o in outcomes if not o.reproduced
    ]
    assert all("not re-executed" in o.detail for o in outcomes)


def test_generation_for_an_external_server_uses_state_mutations_only() -> None:
    scenario = load_scenario(REF)
    worlds, _ = generate_worlds(scenario, attempts=80, depth=1)
    assert worlds and all(not w.world.timers and not w.world.response_edits for w in worlds)
    assert {m.target for w in worlds for m in w.world.path} == {"state"}
