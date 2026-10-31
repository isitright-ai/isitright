"""LLM-proposed hints: the flow, the labels, and the rule that a proposal grants no validity tier.

No model, key or network: a recorded response stands in for the model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.proposals import (
    ProposalError,
    ProposalRequest,
    confirm_proposals,
    load_hints,
    propose_hints,
    write_proposals,
)
from isitright.packs.mcp.generate import generate_worlds
from isitright.packs.mcp.model import McpScenario, ScenarioError, load_scenario, with_hints_file

ROOT = Path(__file__).parents[1]
SHOP_REF = f"{ROOT / 'examples' / 'agents' / 'shop' / 'scenario.py'}:SCENARIO"
FIXTURE = ROOT / "tests" / "fixtures" / "hint_proposals"
sys.path.insert(0, str(ROOT / "examples" / "proposers"))

import model_proposer  # noqa: E402


@pytest.fixture(scope="module")
def shop() -> McpScenario:
    return load_scenario(SHOP_REF)


def _request(shop: McpScenario) -> ProposalRequest:
    return ProposalRequest(
        task=shop.task,
        policy=shop.spec.policy,
        tools=shop.spec.tools,
        schema=shop.spec.schema,
        existing=list(shop.hints),
    )


def _recorded() -> model_proposer.ModelHintProposer:
    text = (FIXTURE / "shop_response.txt").read_text(encoding="utf-8")
    return model_proposer.ModelHintProposer(complete=lambda prompt: text)


def test_the_prompt_carries_the_task_the_tools_and_the_entity_model(shop: McpScenario) -> None:
    prompt = model_proposer.build_prompt(_request(shop))
    assert shop.task[:40] in prompt
    for tool in ("find_customer", "list_orders", "cancel_order (writes)"):
        assert tool in prompt
    assert "orders (key id)" in prompt and "json_path" in prompt


def test_a_recorded_response_gives_proposed_hints_and_the_model_entity_model_rejects_bad_ones(
    shop: McpScenario,
) -> None:
    result = propose_hints(_recorded(), _request(shop))
    assert [h.name for h in result.hints] == ["gate_pending", "newest_first", "nobody"]
    assert {h.provenance for h in result.hints} == {Provenance.PROPOSED}
    reasons = {h.name: why for h, why in result.rejected}
    assert "no field 'created'" in reasons["wrong_field"]
    assert "duplicate hint name" in "".join(reasons.values())


def test_a_response_that_is_not_json_proposes_nothing() -> None:
    assert model_proposer.parse_response("I cannot help with that.") == []
    assert model_proposer.parse_response("```json\n[not json]\n```") == []


def test_no_key_is_read_or_stored_by_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ISITRIGHT_HINT_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        model_proposer.default_complete("prompt")
    source = (ROOT / "examples" / "proposers" / "model_proposer.py").read_text(encoding="utf-8")
    assert source.count("os.environ.get") == 2  # only inside default_complete, at call time


def test_the_file_flow_propose_edit_confirm_load(shop: McpScenario, tmp_path: Path) -> None:
    path = tmp_path / "hints.yaml"
    write_proposals(path, propose_hints(_recorded(), _request(shop)), scenario=shop.id)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {h["status"] for h in document["hints"]} == {"proposed"}
    assert {r["name"] for r in document["rejected_by_the_entity_model"]} == {
        "wrong_field",
        "gate_pending",
    }
    hints = load_hints(path, shop.spec.schema, list(shop.hints))
    assert {h.provenance for h in hints} == {Provenance.PROPOSED}
    assert confirm_proposals(path, ["newest_first"], schema=shop.spec.schema) == ["newest_first"]
    loaded = {h.name: h.provenance for h in load_hints(path, shop.spec.schema, list(shop.hints))}
    assert loaded == {
        "gate_pending": Provenance.PROPOSED,
        "newest_first": Provenance.DECLARED,
        "nobody": Provenance.PROPOSED,
    }
    assert confirm_proposals(path) == ["gate_pending", "nobody"]  # everything still proposed
    with pytest.raises(ProposalError, match="no such hint"):
        confirm_proposals(path, ["missing"])


def test_an_edited_hint_that_no_longer_resolves_cannot_be_confirmed_or_loaded(
    shop: McpScenario, tmp_path: Path
) -> None:
    path = tmp_path / "hints.yaml"
    write_proposals(path, propose_hints(_recorded(), _request(shop)), scenario=shop.id)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["hints"][1]["args"]["field"] = "no_such_field"
    document["hints"][2]["status"] = "rejected"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ProposalError, match="does not resolve"):
        confirm_proposals(path, ["newest_first"], schema=shop.spec.schema)
    with pytest.raises(ProposalError, match="does not resolve"):
        load_hints(path, shop.spec.schema)
    document["hints"][1]["status"] = "rejected"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert [h.name for h in load_hints(path, shop.spec.schema, list(shop.hints))] == [
        "gate_pending"
    ]  # a rejected hint is dropped


def test_a_file_that_is_not_a_hints_file_is_an_error(tmp_path: Path) -> None:
    for text in ("just: text", "- a\n- b", "format: isitright-hints\nhints: 3"):
        bad = tmp_path / "bad.yaml"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ProposalError):
            load_hints(bad, load_scenario(SHOP_REF).spec.schema)


def test_the_scenario_keeps_its_own_hint_when_the_file_repeats_a_name(
    shop: McpScenario, tmp_path: Path
) -> None:
    path = tmp_path / "hints.yaml"
    document = {
        "format": "isitright-hints",
        "hints": [
            {
                "name": "gate",
                "kind": "gate",
                "status": "proposed",
                "args": {"collection": "orders", "field": "status", "allows": ["shipped"]},
            }
        ],
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    merged = with_hints_file(shop, path)
    gate = merged.hints.get("gate")
    assert gate is not None and gate.args["allows"] == ["pending"]
    assert gate.provenance is Provenance.DECLARED
    path.write_text("format: nope", encoding="utf-8")
    with pytest.raises(ScenarioError, match="not an isitright hints file"):
        with_hints_file(shop, path)


def _tiers(scenario: McpScenario) -> dict[str, tuple[str, ...]]:
    worlds, _ = generate_worlds(scenario, attempts=1500, depth=1)
    return {w.world.fingerprint(): tuple(w.tiers) for w in worlds}


def test_proposed_hints_never_raise_a_validity_tier(shop: McpScenario) -> None:
    """The worlds a proposal leads to may differ, and the search order may change. But for any
    world both runs produced, the tiers are identical, and an unsatisfiable proposed lookup does
    not remove TASK_CONSISTENT as a declared one would."""
    proposed = [
        Hint(
            kind="lookup",
            name="guess",
            provenance=Provenance.PROPOSED,
            args={"collection": "customers", "fields": ["name", "zip"], "value": ["No One", "0"]},
        ),
        Hint(
            kind="json_path",
            name="guess_qty",
            provenance=Provenance.PROPOSED,
            args={"path": "orders.items[*].qty"},
        ),
    ]
    with_proposals = McpScenario(
        id=shop.id,
        task=shop.task,
        spec=shop.spec,
        tools=shop.tools,
        base=shop.base,
        layout=shop.layout,
        oracle=shop.oracle,
        hints=Hints([*shop.hints, *proposed]),
        fixed_worlds=shop.fixed_worlds,
        fidelity=shop.fidelity,
    )
    before, after = _tiers(shop), _tiers(with_proposals)
    common = set(before) & set(after)
    assert len(common) > 50
    assert all(before[f] == after[f] for f in common)
    declared = Hints(
        [*shop.hints, proposed[0].model_copy(update={"provenance": Provenance.DECLARED})]
    )
    as_declared = McpScenario(
        id=shop.id,
        task=shop.task,
        spec=shop.spec,
        tools=shop.tools,
        base=shop.base,
        layout=shop.layout,
        oracle=shop.oracle,
        hints=declared,
        fidelity=shop.fidelity,
    )
    confirmed = _tiers(as_declared)
    assert all("TASK_CONSISTENT" not in tiers for tiers in confirmed.values())  # declared: gone
    assert any("TASK_CONSISTENT" in tiers for tiers in after.values())  # proposed: still granted


def test_the_cli_proposes_confirms_and_rejects_without_trust(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "hints.yaml"
    args = [
        "agents",
        "hints",
        "propose",
        "--scenario",
        SHOP_REF,
        "--proposer",
        f"{FIXTURE / 'proposer.py'}:PROPOSER",
        "--output",
        str(out),
    ]
    refused = runner.invoke(app, args)
    assert refused.exit_code == 2 and "--trust-code" in refused.output
    done = runner.invoke(app, [*args, "--trust-code"])
    assert done.exit_code == 0, done.output
    assert "3 hint(s) proposed, 2 rejected" in done.output
    assert runner.invoke(app, [*args, "--trust-code"]).exit_code == 2  # the file exists
    confirm = runner.invoke(
        app, ["agents", "hints", "confirm", str(out), "--accept", "newest_first"]
    )
    assert confirm.exit_code == 0 and "newest_first" in confirm.output
    checked = runner.invoke(
        app,
        ["agents", "hints", "confirm", str(out), "--scenario", SHOP_REF, "--trust-code"],
    )
    assert checked.exit_code == 0 and "gate_pending" in checked.output
    assert (
        runner.invoke(
            app, ["agents", "hints", "confirm", str(out), "--scenario", SHOP_REF]
        ).exit_code
        == 2
    )
    missing = runner.invoke(app, ["agents", "hints", "confirm", str(out), "--accept", "zzz"])
    assert missing.exit_code == 2 and "no such hint" in missing.output
    bad_ref = runner.invoke(
        app,
        [
            "agents",
            "hints",
            "propose",
            "--scenario",
            SHOP_REF,
            "--proposer",
            "nope:nothing",
            "--output",
            str(tmp_path / "x.yaml"),
            "--trust-code",
        ],
    )
    assert bad_ref.exit_code == 2
