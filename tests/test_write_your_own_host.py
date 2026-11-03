"""The user-written host example uses only core interfaces and finds a defect in a CLI program."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE = Path(__file__).parents[1] / "examples" / "hosts" / "table_cli"


@pytest.fixture(scope="module")
def host_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("table_cli_host", EXAMPLE / "host.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["table_cli_host"] = module
    spec.loader.exec_module(module)
    return module


def test_the_example_imports_nothing_from_a_pack() -> None:
    source = (EXAMPLE / "host.py").read_text(encoding="utf-8")
    assert "isitright.packs" not in source
    assert "isitright.core" in source


def test_the_host_loads_a_world_runs_the_program_and_reads_the_output_table(
    host_module: ModuleType,
) -> None:
    from isitright.core.mutations import World

    host = host_module.CliTableHost()
    world = World(host_module.initial_state())
    with host.prepare(host_module.SPEC, world) as prepared:
        table = prepared.run([])
    assert {r["region"]: float(r["mean"]) for r in table} == {"north": 15.0, "south": 30.0}
    assert host_module.compare(world.state, table).matches
    assert host.fidelity.value == "NATIVE_ISOLATED"


def test_a_correct_program_has_no_counterexample(host_module: ModuleType) -> None:
    assert host_module.audit([], attempts=60)["found"] is False


def test_a_defective_program_gives_a_minimized_counterexample(host_module: ModuleType) -> None:
    result = host_module.audit(["--integer-mean"], attempts=120)
    assert result["found"] is True and result["rows"] <= 3
