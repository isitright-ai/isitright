"""P6: a data file name that names the output directory itself, or that Windows would rewrite, is an
invalid name: exit code 2 and a one-line message, not a traceback."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.paths import UnsafePathError, contained_path

from . import test_report_paths as _paths

_copy_report = _paths._copy_report
_save = _paths._save
data_report = _paths.data_report  # the module-scoped fixture that audits a small data task

runner = CliRunner()

NAMES = [
    ".",
    "",
    "..",
    "./",
    ".\\",
    "a/.",
    "a/./b",
    "name.",
    "name ",
    "dir/name.",
    " ",
    "...",
    "a. ",
]


@pytest.mark.parametrize("name", NAMES)
def test_contained_path_refuses_a_name_that_is_the_directory_or_that_windows_rewrites(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(UnsafePathError, match="unsafe path"):
        contained_path(tmp_path, name)


@pytest.mark.parametrize("name", ["orders.csv", ".hidden", "a.b", "dir/orders.csv", "x y.csv"])
def test_ordinary_names_are_still_accepted(tmp_path: Path, name: str) -> None:
    assert contained_path(tmp_path, name).is_relative_to(tmp_path)


@pytest.mark.parametrize("name", NAMES)
def test_data_export_rejects_the_name_with_exit_code_2_and_one_line(
    data_report: Path,
    tmp_path: Path,
    name: str,
) -> None:
    report, data = _copy_report(data_report, tmp_path)
    finding = data["cases"][0]["findings"][0]
    finding["divergence"]["data_files"] = {name: "owned", "orders.csv": "a,b\n1,2\n"}
    _save(report, data)
    result = runner.invoke(app, ["data", "export", str(report), "--output", str(tmp_path / "out")])
    assert result.exit_code == 2, result.output
    assert not isinstance(result.exception, Exception) or isinstance(result.exception, SystemExit)
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, result.output
    assert lines[0].startswith("Input error: unsafe data file name")
    assert "Traceback" not in result.output
