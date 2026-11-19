"""A path or name read from a report never reaches outside the directory it belongs to (H1).

A report is an input anyone can write. Each pack's ``export`` and ``replay`` is fed a crafted report
(a relative escape, an absolute path, a Windows drive, a symbolic link) and must exit with the
invalid-input code, with nothing written outside the output directory and nothing read outside
the report's directory. Where a read outside would have succeeded, a valid file is planted there, so
a missing refusal shows up as a successful command.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.paths import UnsafePathError, contained_path

runner = CliRunner()

BAD_NAMES = [
    "../escape.txt",
    "..\\escape.txt",
    "sub/../../escape.txt",
    "sub\\..\\..\\escape.txt",
    "/abs/escape.txt",
    "\\rooted\\escape.txt",
    "C:\\escape.txt",
    "C:/escape.txt",
    "C:escape.txt",
    "\\\\server\\share\\escape.txt",
    "file.txt:stream",
    "..",
    "",
    "a\0b",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_contained_path_refuses_every_escape(tmp_path: Path, name: str) -> None:
    with pytest.raises(UnsafePathError, match="unsafe path"):
        contained_path(tmp_path, name)


def test_contained_path_refuses_an_absolute_path_inside_the_base(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError, match="absolute"):
        contained_path(tmp_path, str(tmp_path / "inside.txt"))


@pytest.mark.parametrize(
    "name", ["a.txt", "dir/b.txt", "dir\\c.txt", "findings/x_1/replay.json", "orders.csv"]
)
def test_contained_path_accepts_plain_relative_names(tmp_path: Path, name: str) -> None:
    path = contained_path(tmp_path, name)
    assert path.is_relative_to(tmp_path)
    assert path.name == name.replace("\\", "/").split("/")[-1]


def test_contained_path_refuses_a_symbolic_link_out_of_the_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    try:
        (base / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    with pytest.raises(UnsafePathError, match="outside"):
        contained_path(base, "link/escape.txt")


def test_contained_path_names_what_it_checked(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError, match="unsafe data file name"):
        contained_path(tmp_path, "../x", what="data file name")


def _spellings(planted: Path) -> list[str]:
    """A relative escape, an absolute path and a Windows drive, all naming ``planted``."""
    return [f"../{planted.name}", str(planted.resolve()), f"C:\\{planted.name}"]


def _copy_report(source: Path, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    target = tmp_path / "audit"
    shutil.copytree(source.parent, target)
    return target / "report.json", json.loads((target / "report.json").read_text("utf-8"))


def _save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---- data pack -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def data_report(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("pandas")
    from isitright.packs.data.programs import write_programs
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    root = tmp_path_factory.mktemp("data-paths")
    task = make_task(root / "orders")
    programs = root / "programs.jsonl"
    write_programs(programs, [program(DROPNA_FORGOTTEN, "mistake")])
    out = root / "out"
    args = ["data", "check", str(task), "--programs", str(programs), "--output", str(out)]
    result = runner.invoke(app, [*args, "--trust-code", "--attempts", "60", "--reuse", "20"])
    assert result.exit_code == 0, result.output
    return out / "report.json"


@pytest.mark.parametrize("which", [0, 1, 2])
def test_data_export_refuses_data_file_names_that_leave_the_output_directory(
    data_report: Path, tmp_path: Path, which: int
) -> None:
    report, data = _copy_report(data_report, tmp_path)
    escape = tmp_path / "escape.txt"
    finding = data["cases"][0]["findings"][0]
    finding["divergence"]["data_files"] = {
        _spellings(escape)[which]: "owned",
        "orders.csv": "a,b\n1,2\n",
    }
    _save(report, data)
    result = runner.invoke(app, ["data", "export", str(report), "--output", str(tmp_path / "out")])
    assert result.exit_code == 2, result.output
    assert "unsafe data file name" in result.output
    assert not escape.exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_data_export_refuses_a_finding_id_that_walks_out(data_report: Path, tmp_path: Path) -> None:
    report, data = _copy_report(data_report, tmp_path)
    data["cases"][0]["findings"][0]["finding_id"] = ".."
    _save(report, data)
    output = tmp_path / "cases"
    result = runner.invoke(app, ["data", "export", str(report), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert not (output / "gold.py").exists() and not (output / "expected.json").exists()


def test_data_write_report_refuses_names_that_leave_the_output_directory(
    data_report: Path, tmp_path: Path
) -> None:
    from isitright.core.evidence import AuditReport
    from isitright.packs.data.reports import write_report

    _, data = _copy_report(data_report, tmp_path)
    data["cases"][0]["findings"][0]["divergence"]["data_files"] = {"../../escape.txt": "owned"}
    report = AuditReport.model_validate(data)
    with pytest.raises(UnsafePathError, match="unsafe data file name"):
        write_report(report, tmp_path / "out", {})
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("which", [0, 1, 2])
def test_data_replay_refuses_an_artifact_path_outside_the_report_directory(
    data_report: Path, tmp_path: Path, which: int
) -> None:
    report, data = _copy_report(data_report, tmp_path)
    finding = data["cases"][0]["findings"][0]
    planted = tmp_path / "outside-replay.json"
    shutil.copy(report.parent / finding["replay"]["artifact"], planted)
    finding["replay"]["artifact"] = _spellings(planted)[which]
    _save(report, data)
    result = runner.invoke(app, ["data", "replay", str(report), "--trust-code"])
    assert result.exit_code == 2, result.output
    assert "unsafe replay artifact" in result.output
    assert "Reproduced" not in result.output


# ---- research pack ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def research_report(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tests.research_fixtures import ROOT

    out = tmp_path_factory.mktemp("research-paths") / "out"
    args = ["research", "check", str(ROOT / "corpus"), "--task", str(ROOT / "task.json")]
    result = runner.invoke(
        app, [*args, "--output", str(out), "--stand-in", "credulous", "--depth", "1"]
    )
    assert result.exit_code == 0, result.output
    return out / "report.json"


@pytest.mark.parametrize("which", [0, 1, 2])
def test_research_export_refuses_an_artifact_path_outside_the_report_directory(
    research_report: Path, tmp_path: Path, which: int
) -> None:
    report, data = _copy_report(research_report, tmp_path)
    finding = data["cases"][0]["findings"][0]
    planted = tmp_path / "outside.replay.json"
    shutil.copy(report.parent / finding["replay"]["artifact"], planted)
    finding["replay"]["artifact"] = _spellings(planted)[which]
    _save(report, data)
    output = tmp_path / "cases"
    result = runner.invoke(app, ["research", "export", str(report), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert "unsafe replay artifact" in result.output
    assert not list(output.glob("*.eval-case.json"))


@pytest.mark.parametrize("identifier", ["research:../../escape", "research:/abs/escape"])
def test_research_export_refuses_a_finding_id_used_as_a_file_name(
    research_report: Path, tmp_path: Path, identifier: str
) -> None:
    report, data = _copy_report(research_report, tmp_path)
    data["cases"][0]["findings"][0]["finding_id"] = identifier
    _save(report, data)
    output = tmp_path / "cases"
    result = runner.invoke(app, ["research", "export", str(report), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert "unsafe finding id" in result.output
    assert not list(tmp_path.rglob("escape.eval-case.json"))


@pytest.mark.skipif(os.name == "nt", reason="creating links needs a privilege on Windows")
def test_research_export_refuses_an_artifact_reached_through_a_link(
    research_report: Path, tmp_path: Path
) -> None:
    report, data = _copy_report(research_report, tmp_path)
    finding = data["cases"][0]["findings"][0]
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    shutil.copy(report.parent / finding["replay"]["artifact"], outside / "linked.replay.json")
    (report.parent / "via").symlink_to(outside, target_is_directory=True)
    finding["replay"]["artifact"] = "via/linked.replay.json"
    _save(report, data)
    output = tmp_path / "cases"
    result = runner.invoke(app, ["research", "export", str(report), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert "outside" in result.output


# ---- agents (MCP) pack -----------------------------------------------------------------------

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"


@pytest.fixture(scope="module")
def agents_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from isitright.packs.mcp.audit import run_scenario

    output = tmp_path_factory.mktemp("agents-paths") / "out"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEMO_AGENT_MODE", "careless")
        run_scenario(
            scenario_ref=f"{EXAMPLES / 'booking_scenario.py'}:SCENARIO",
            agent_command=f'"{sys.executable}" "{EXAMPLES / "demo_agent.py"}"',
            output_dir=output,
            worlds="fixed",
            k=1,
            only=["booked_24h_01m", "flight_cancelled"],
            trust_code=True,
            timeout_seconds=120,
        )
    return output / "report.json"


@pytest.mark.parametrize("which", [0, 1, 2])
def test_agents_export_refuses_a_run_directory_outside_the_report_directory(
    agents_output: Path, tmp_path: Path, which: int
) -> None:
    report, data = _copy_report(agents_output, tmp_path)
    finding = data["cases"][0]["findings"][0]
    example = finding["divergence"]["example_run_dir"]
    planted = tmp_path / "outside-run"
    shutil.copytree(report.parent / example, planted)
    spelled = _spellings(planted)[which]
    for run in data["cases"][0]["extensions"]["mcp"]["runs"]:
        if run["run_dir"] == example:
            run["run_dir"] = spelled
    finding["divergence"]["example_run_dir"] = spelled
    _save(report, data)
    output = tmp_path / "cases.jsonl"
    result = runner.invoke(app, ["agents", "export", str(report), "--output", str(output)])
    assert result.exit_code == 2, result.output
    assert "unsafe run directory" in result.output
    assert not output.exists()


@pytest.mark.parametrize("which", [0, 1, 2])
def test_agents_replay_refuses_a_run_directory_outside_the_report_directory(
    agents_output: Path, tmp_path: Path, which: int
) -> None:
    report, data = _copy_report(agents_output, tmp_path)
    run = data["cases"][0]["extensions"]["mcp"]["runs"][0]
    planted = tmp_path / "outside-run"
    shutil.copytree(report.parent / run["run_dir"], planted)
    run["run_dir"] = _spellings(planted)[which]
    _save(report, data)
    result = runner.invoke(app, ["agents", "replay", "--report", str(report), "--trust-code"])
    assert result.exit_code == 2, result.output
    assert "unsafe run directory" in result.output
    assert "reproduced" not in result.output.replace("unsafe run directory", "")
