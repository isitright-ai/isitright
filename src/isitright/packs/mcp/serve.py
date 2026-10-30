"""Serve one world of a scenario as a stdio MCP server.

The agent's MCP client launches this module from the injected ``mcp.json``. One process is one
fresh world: it builds the service state, serves the scenario's tools, applies the world's response
edits and timers, appends every call to ``trace.jsonl`` and keeps ``state_after.json`` current, so
the runner can read the final state from outside the process (hidden from the agent). stdout
carries the protocol, so nothing else may print to it.

    python -m isitright.packs.mcp.serve --scenario module:attr --world-file FILE --run-dir DIR
        --trust-code        (or --fixed ID instead of --world-file for a hand-written world)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from isitright.core.mutations import World
from isitright.core.world import State
from isitright.packs.mcp.host import HostTool, build_server, serve_stdio
from isitright.packs.mcp.model import (
    WORLD_CHANGE,
    FixedWorld,
    Interference,
    McpScenario,
    ScenarioError,
    ServiceState,
    load_scenario,
)
from isitright.packs.mcp.runtime import ServiceRuntime
from isitright.packs.mcp.trace import TraceEvent, TraceRecorder


def write_state(path: Path, state: ServiceState) -> None:
    """Replace ``path`` atomically so a reader never sees a half-written state."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def world_of(scenario: McpScenario, fixed: FixedWorld) -> tuple[World, tuple[Interference, ...]]:
    """A hand-written world as a core world plus its callable interferences."""
    service = fixed.build()
    state = scenario.layout.from_service(service, scenario.base.keys)
    return World(state), tuple(fixed.interferences)


def build_world_server(
    scenario: McpScenario,
    world: World,
    run_dir: Path,
    interferences: tuple[Interference, ...] = (),
) -> Any:
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime = ServiceRuntime.for_world(scenario, world, interferences)
    state_after = run_dir / "state_after.json"
    write_state(run_dir / "state_before.json", runtime.service)
    write_state(state_after, runtime.service)
    specs = [HostTool(t.name, t.description, t.input_schema) for t in scenario.tools]
    trace_path = run_dir / "trace.jsonl"

    def persist(event: TraceEvent) -> None:
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.__dict__, sort_keys=True, default=str) + "\n")

    def handler(name: str, arguments: dict[str, Any]) -> str:
        try:
            return runtime.call(name, arguments)
        finally:
            write_state(state_after, runtime.service)

    trace = TraceRecorder(on_record=persist)

    def after_call(name: str, arguments: dict[str, Any], is_error: bool) -> None:
        if is_error:
            return
        for change in runtime.after_call(name, arguments):
            trace.record(WORLD_CHANGE, change, "", is_error=False)
        write_state(state_after, runtime.service)

    return build_server(scenario.id, specs, handler, trace, after_call)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m isitright.packs.mcp.serve")
    parser.add_argument("--scenario", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--world-file", type=Path)
    group.add_argument("--fixed")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--trust-code",
        action="store_true",
        help="Required: the scenario is imported and executed.",
    )
    args = parser.parse_args(argv)
    if not args.trust_code:
        print("refusing to import a scenario without --trust-code", file=sys.stderr)
        return 2
    try:
        scenario = load_scenario(args.scenario)
        if args.fixed:
            world, interferences = world_of(scenario, scenario.fixed(args.fixed))
        else:
            data = json.loads(args.world_file.read_text(encoding="utf-8"))
            world, interferences = World.from_json(data), ()
        server = build_world_server(scenario, world, args.run_dir, interferences)
    except ScenarioError as error:
        print(str(error), file=sys.stderr)
        return 2
    serve_stdio(server)
    return 0


def state_of(scenario: McpScenario, service: ServiceState) -> State:
    return scenario.layout.from_service(service, scenario.base.keys)


if __name__ == "__main__":
    raise SystemExit(main())
