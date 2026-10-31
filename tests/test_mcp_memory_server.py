"""The Memory reference MCP server (third-party, Node) as the service. Skipped without Node and the
package (``npm install --prefix .tools/third-party @modelcontextprotocol/server-memory``).

The host, generator and oracle run on a server isitright did not write. The scripted agents and
the oracle are the host author's, so this shows the machinery works, not that the oracle is
independent of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from isitright.core.mutations import World
from isitright.core.oracles import Role
from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.generate import generate_worlds
from isitright.packs.mcp.model import load_scenario
from isitright.packs.mcp.oracle import reference_outcome

MEMORY = Path(__file__).parents[1] / "examples" / "agents" / "memory"
REF = f"{MEMORY / 'scenario.py'}:SCENARIO"
sys.path.insert(0, str(MEMORY))

import scenario as memory  # noqa: E402

pytestmark = pytest.mark.skipif(
    not memory.available(), reason="Node and @modelcontextprotocol/server-memory not installed"
)
AGENT = f'"{sys.executable}" "{MEMORY / "scripted_agent.py"}"'


def test_the_reference_procedure_runs_on_the_real_server_and_roles_follow_the_graph() -> None:
    scenario = load_scenario(REF)
    base = reference_outcome(scenario, World(scenario.base))
    assert base.role is Role.CONTROL and base.after is not None
    assert base.after["entities"]["Alice Chen"]["observations"] == [
        "prefers email",
        "works at Beta Corp",
    ]
    moved = scenario.base.evolve(
        {
            "entities": [
                {
                    **e,
                    "observations": ["works at Beta Corp"]
                    if e["name"] == "Alice Chen"
                    else e["observations"],
                }
                for e in scenario.base.entities("entities")
            ]
        }
    )
    assert reference_outcome(scenario, World(moved)).role is Role.TRAP  # already moved: do nothing


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    out = {}
    for mode in ("reference", "careless", "refuse"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("MEMORY_AGENT_MODE", mode)
            out[mode] = run_scenario(
                scenario_ref=REF,
                agent_command=AGENT,
                output_dir=tmp_path_factory.mktemp(mode) / "out",
                worlds="generated",
                k=1,
                attempts=60,
                max_worlds=6,
                sequential=False,
                trust_code=True,
                timeout_seconds=120,
            )
    return out


def test_scripted_agents_are_told_apart_on_the_third_party_server(runs: dict[str, object]) -> None:
    cases = {m: r.cases[0] for m, r in runs.items()}  # type: ignore[attr-defined]
    assert cases["reference"].divergence_status.value != "COUNTEREXAMPLE_FOUND"
    assert cases["careless"].findings and cases["refuse"].findings
    baseline = next(w for w in cases["careless"].worlds if w.id == "baseline")
    assert baseline.counts["not_met"] == 1  # the careless agent leaves the Acme fact in place
    assert cases["careless"].execution_fidelity.found_on == "NATIVE_ISOLATED"
    violated = {
        o.name for f in cases["careless"].findings for o in f.oracles if o.kind == "INVARIANT"
    }
    assert violated <= {"only_alice_changes", "no_other_entity_created"}


def test_generation_on_a_graph_server_uses_the_generic_families() -> None:
    scenario = load_scenario(REF)
    worlds, _ = generate_worlds(scenario, attempts=60, depth=1)
    assert worlds
    families = {f for w in worlds for f in w.families}
    assert "duplicate" in families  # the generic families act on the graph's entities
    assert all(w.role is not Role.UNJUDGEABLE or w.role_basis for w in worlds)
