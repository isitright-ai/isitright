"""The MCP pack's scenario: a declared world spec, a simulated service and an oracle.

A scenario is trusted local Python (it is imported, so the CLI needs ``--trust-code``). It declares
what states can exist (an entity schema and constraints), the tools and their simulated handlers,
service parameters, hints from the task text, and an oracle: invariants over ``(before, after,
trace)`` and a reference procedure that recomputes the right behavior in any world. Worlds are
generated from this by the core's families; hand-written worlds may be added as ``FixedWorld``
regression fixtures.

The service state the handlers see is a JSON-compatible ``dict``. ``Layout`` maps it to and from the
entity state, so handlers, invariants and reference procedures written against the service's own
shape keep working on generated worlds.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from isitright.core.hints import Hints
from isitright.core.hosts import Fidelity
from isitright.core.spec import WorldSpec
from isitright.core.world import State

ServiceState = dict[str, Any]
Handler = Callable[[ServiceState, dict[str, Any]], Any]
TraceDict = dict[str, Any]
WORLD_CHANGE = "__world_change__"
"""Trace name of the pseudo-event recorded when the world changes during a run. It is not a tool
call: counts of calls exclude it, and replay re-applies the change instead of calling it."""

_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class ScenarioError(ValueError):
    """The scenario definition or reference is invalid."""


@dataclass(frozen=True)
class ToolDef:
    """A tool with its simulated handler. ``writes`` marks state-changing tools in the report."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    writes: bool = False


@dataclass(frozen=True)
class Interference:
    """A hand-written change to the world during a run, fired once, just after a matching call.

    Kept for hand-written fixture worlds; generated worlds use declarative timers. ``when`` sees
    the service state after the call, the tool name and its arguments. ``apply`` mutates the
    state in place and returns a JSON description that becomes the change event's arguments.
    """

    name: str
    when: Callable[[ServiceState, str, dict[str, Any]], bool]
    apply: Callable[[ServiceState], dict[str, Any]]


@dataclass(frozen=True)
class Invariant:
    """A property that must hold in every run: returns violation messages, empty if it holds."""

    name: str
    description: str
    check: Callable[[ServiceState, ServiceState, list[TraceDict]], list[str]]


@dataclass(frozen=True)
class Expectation:
    """A hand-written statement of the right behavior in one fixed world."""

    name: str
    description: str
    met: Callable[[ServiceState, ServiceState, list[TraceDict]], bool]


@dataclass(frozen=True)
class FixedWorld:
    """A hand-written world kept as a regression fixture. Its role is the author's label."""

    id: str
    role: Literal["baseline", "trap", "control"]
    description: str
    build: Callable[[], ServiceState]
    validate: Callable[[ServiceState], list[str]] | None = None
    expectation: Expectation | None = None
    interferences: Sequence[Interference] = ()


@dataclass(frozen=True)
class Layout:
    """How the entity state maps onto the service's own JSON shape."""

    keyed: tuple[str, ...]
    """Collections stored as ``{key: entity}``."""
    listed: tuple[str, ...] = ()
    """Collections stored as a list."""
    scalars: tuple[str, ...] = ("now",)
    """Parameters stored at the top level of the service state."""
    block: str = "service"
    """Where the remaining parameters live (None-valued ones are left out)."""
    defaults: dict[str, Any] = field(default_factory=dict)

    def to_service(self, state: State) -> ServiceState:
        out: ServiceState = {}
        for name in self.scalars:
            if name in state.params:
                out[name] = copy.deepcopy(state.params[name])
        params = {
            **self.defaults,
            **{k: v for k, v in state.params.items() if k not in self.scalars},
        }
        out[self.block] = {k: copy.deepcopy(v) for k, v in params.items() if v is not None}
        for name in self.keyed:
            key = state.keys[name]
            out[name] = {e[key]: copy.deepcopy(e) for e in state.entities(name)}
        for name in self.listed:
            out[name] = [copy.deepcopy(e) for e in state.entities(name)]
        return out

    def from_service(self, data: ServiceState, keys: Mapping[str, str]) -> State:
        collections: dict[str, tuple[dict[str, Any], ...]] = {}
        for name in self.keyed:
            collections[name] = tuple(copy.deepcopy(e) for e in data.get(name, {}).values())
        for name in self.listed:
            collections[name] = tuple(copy.deepcopy(e) for e in data.get(name, []))
        params: dict[str, Any] = {n: copy.deepcopy(data[n]) for n in self.scalars if n in data}
        for key, value in (data.get(self.block) or {}).items():
            params[key] = copy.deepcopy(value)
        return State(collections, keys, params)


Caller = Callable[..., dict[str, Any]]
"""``call(tool, **arguments)`` returns the parsed JSON result or raises `ToolCallError`."""


class ToolCallError(Exception):
    """A tool returned an error result."""


@dataclass
class ScenarioOracle:
    """What is right in any world, written by someone other than the world's author.

    ``reference`` drives a `Caller` through the tools the way a careful agent would; whether it
    writes decides the world's role (it acts: a control; it does nothing: a trap). The agent's
    final state is compared with the state the reference leaves behind (``normalize`` removes
    service-assigned detail such as generated ids). ``judgeable`` returns a reason when a world is
    outside the oracle's stated assumptions, and the oracle then says it cannot judge.
    """

    name: str
    invariants: Sequence[Invariant]
    reference: Callable[[Caller], None]
    normalize: Callable[[ServiceState], Any] = lambda state: state
    normalize_call: Callable[[str, dict[str, Any]], Any] = lambda tool, args: (
        tool,
        json.dumps(args, sort_keys=True),
    )
    """Reduces a write call to what matters (drop free text such as a reason) for comparing the
    agent's successful writes with the reference's: "exactly once" is part of the right behavior."""
    judgeable: Callable[[Any], str | None] = lambda world: None
    assumptions: Sequence[str] = ()
    description: str = "the reference procedure's final state"


@dataclass
class McpScenario:
    id: str
    task: str
    spec: WorldSpec
    tools: Sequence[ToolDef]
    base: State
    layout: Layout
    oracle: ScenarioOracle
    hints: Hints = field(default_factory=Hints)
    fixed_worlds: Sequence[FixedWorld] = ()
    fidelity: Fidelity = Fidelity.SIMULATED

    def __post_init__(self) -> None:
        if not _ID.match(self.id):
            raise ScenarioError(f"scenario id {self.id!r} must match {_ID.pattern}")
        if not self.tools:
            raise ScenarioError("a scenario needs at least one tool")
        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            raise ScenarioError(f"duplicate tool names in scenario {self.id}")
        if WORLD_CHANGE in names:
            raise ScenarioError(f"{WORLD_CHANGE} is reserved and cannot be a tool name")
        ids = [w.id for w in self.fixed_worlds]
        if len(set(ids)) != len(ids):
            raise ScenarioError(f"duplicate world names in scenario {self.id}")
        for world in self.fixed_worlds:
            if not _ID.match(world.id):
                raise ScenarioError(f"world id {world.id!r} must match {_ID.pattern}")
            if world.role == "control" and world.expectation is None:
                raise ScenarioError(f"control world {world.id} needs an expectation")
            names_i = [i.name for i in world.interferences]
            if len(set(names_i)) != len(names_i):
                raise ScenarioError(f"duplicate interference names in world {world.id}")
        spec_tools = {t.name for t in self.spec.tools}
        if spec_tools != set(names):
            raise ScenarioError("the spec's tools must match the scenario's tool definitions")
        try:
            self.hints.validate(self.spec.schema)
        except ValueError as error:
            raise ScenarioError(str(error)) from error

    def tool(self, name: str) -> ToolDef | None:
        return next((t for t in self.tools if t.name == name), None)

    def fixed(self, world_id: str) -> FixedWorld:
        for world in self.fixed_worlds:
            if world.id == world_id:
                return world
        raise ScenarioError(f"scenario {self.id} has no world {world_id!r}")


def render(result: Any) -> str:
    """Tool results are text: strings pass through, everything else is canonical JSON."""
    return result if isinstance(result, str) else json.dumps(result, sort_keys=True, default=str)


def split_reference(ref: str) -> tuple[str, str]:
    """Split ``module:attr`` or ``path/to/file.py:attr`` on the last colon."""
    module, sep, attribute = ref.rpartition(":")
    if not sep or not module or not attribute:
        raise ScenarioError(
            f"scenario reference {ref!r} must look like 'module:attr' or 'file.py:attr'"
        )
    return module, attribute


def _is_file_reference(module: str) -> bool:
    return module.endswith(".py") or "/" in module or "\\" in module


def absolute_reference(ref: str) -> str:
    """Make a file reference absolute so a child process can import it from any directory."""
    module, attribute = split_reference(ref)
    if _is_file_reference(module):
        return f"{Path(module).resolve()}:{attribute}"
    return ref


def load_scenario(ref: str) -> McpScenario:
    """Import and return a scenario. Executes the referenced code: trusted local use only."""
    module_name, attribute = split_reference(ref)
    try:
        if _is_file_reference(module_name):
            path = Path(module_name).resolve()
            spec = importlib.util.spec_from_file_location(f"_isitright_scenario_{path.stem}", path)
            if spec is None or spec.loader is None:
                raise ScenarioError(f"cannot import scenario file {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            sys.path.insert(0, str(path.parent))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.remove(str(path.parent))
        else:
            module = importlib.import_module(module_name)
        value = getattr(module, attribute)
    except ScenarioError:
        raise
    except (ImportError, AttributeError, OSError, SyntaxError) as error:
        raise ScenarioError(f"cannot load scenario {ref!r}: {error}") from error
    if callable(value) and not isinstance(value, McpScenario):
        value = value()
    if not isinstance(value, McpScenario):
        raise ScenarioError(f"{ref!r} is not a McpScenario")
    return value
