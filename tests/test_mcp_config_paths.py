"""runs/*/mcp.json names no location of the machine that wrote it.

The runner writes ``mcp.json`` with absolute paths so the agent's MCP client can start the server
from any working directory. Once the run is over the file is a record: the paths inside the output
directory are rewritten relative to it and the scenario is the reference as the user typed it, so a
report directory that is copied elsewhere carries no path of the original machine. The interpreter
that started the server (``command``) is not a path inside the output directory and stays.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from isitright.packs.mcp.audit import run_scenario
from isitright.packs.mcp.runner import record_mcp_config

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"
TYPED = f"{EXAMPLES / 'booking_scenario.py'}:SCENARIO"


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("original-mcp-location") / "out"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", "careless")
        run_scenario(
            scenario_ref=TYPED,
            agent_command=f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"',
            output_dir=out,
            worlds="fixed",
            k=1,
            only=["booked_24h_01m", "flight_cancelled"],
            trust_code=True,
            timeout_seconds=120,
        )
    return out


def _server(path: Path) -> dict[str, object]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return config["mcpServers"]["isitright"]  # type: ignore[no-any-return]


def test_paths_inside_the_output_directory_are_relative_to_it(output: Path) -> None:
    configs = sorted(output.glob("runs/*/*/mcp.json"))
    assert len(configs) >= 3
    for config in configs:
        run = config.parent.relative_to(output).as_posix()
        args = _server(config)["args"]
        assert isinstance(args, list)
        assert args[args.index("--run-dir") + 1] == run
        if "--world-file" in args:
            assert args[args.index("--world-file") + 1] == f"{run}/world.json"
        assert args[args.index("--scenario") + 1] == TYPED
        text = config.read_text(encoding="utf-8")
        assert str(output) not in text and output.as_posix() not in text
        assert str(output).replace("\\", "\\\\") not in text


def test_the_record_keeps_the_arguments_that_are_not_paths(output: Path) -> None:
    for config in output.glob("runs/*/*/mcp.json"):
        args = _server(config)["args"]
        assert isinstance(args, list)
        assert args[:3] == ["-m", "isitright.packs.mcp.serve", "--scenario"]
        assert "--trust-code" in args


def test_no_file_in_the_run_directories_names_the_output_directory_except_the_agent_log(
    output: Path,
) -> None:
    """The agent's own stdout (agent.log) is whatever the agent printed; everything isitright wrote
    is free of the output directory."""
    needles = {str(output), output.as_posix(), str(output).replace("\\", "\\\\")}
    leaks = [
        str(path.relative_to(output))
        for path in output.glob("runs/**/*")
        if path.is_file()
        and path.name != "agent.log"
        and any(n in path.read_text(encoding="utf-8", errors="replace") for n in needles)
    ]
    assert not leaks, leaks


def test_a_path_outside_the_output_directory_is_left_as_it_is(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run = out / "runs" / "w" / "1"
    run.mkdir(parents=True)
    elsewhere = str(tmp_path / "elsewhere" / "world.json")
    config = run / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "isitright": {
                        "command": "python",
                        "args": ["--world-file", elsewhere, "--run-dir", str(run)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    record_mcp_config(config, out, scenario_ref="s.py:S")
    args = _server(config)["args"]
    assert args == ["--world-file", elsewhere, "--run-dir", "runs/w/1"]
