"""Pandas is an optional extra: the core, the SQL and MCP packs and the CLI work without it."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def run_without_pandas(code: str) -> subprocess.CompletedProcess[str]:
    blocked = ("pandas", "numpy", "scipy", "pandera", "pyarrow")
    prelude = f"import sys\nfor name in {blocked}:\n    sys.modules[name] = None\n"
    return subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_core_and_the_other_packs_import_without_pandas() -> None:
    result = run_without_pandas(
        """
        import isitright
        import isitright.core.families, isitright.core.evidence, isitright.core.selection
        import isitright.core.compare, isitright.core.hints
        import isitright.packs.sql, isitright.packs.mcp.audit
        import isitright.cli
        import isitright.packs.data
        import isitright.packs.data.cli
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_the_sql_check_runs_without_pandas(tmp_path: Path) -> None:
    result = run_without_pandas(
        """
        from isitright.core.compare import NumericComparator
        from isitright.packs.sql.comparison import compare_results
        assert NumericComparator(1e-9, 0.0, "x").compare(1.0, 1.0).matches
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr


def test_the_data_command_says_what_to_install_when_pandas_is_missing(tmp_path: Path) -> None:
    (tmp_path / "p.jsonl").write_text("", encoding="utf-8")
    result = run_without_pandas(
        f"""
        from typer.testing import CliRunner
        from isitright.cli import app
        args = ["data", "check", {str(tmp_path)!r}, "--programs", {str(tmp_path / "p.jsonl")!r}]
        out = CliRunner().invoke(app, args + ["--output", {str(tmp_path / "o")!r}, "--trust-code"])
        print(out.exit_code)
        print(out.output)
        """
    )
    assert "isitright[data]" in result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "2" or "isitright[data]" in result.stdout


@pytest.mark.parametrize(
    ("module", "needs_pandas"),
    [
        ("mapping", True),
        ("host", True),
        ("audit", True),
        ("live", True),
        ("hints", True),
        ("comparison", False),
        ("programs", False),
        ("reports", True),
    ],
)
def test_the_data_modules_need_pandas_only_where_they_use_it(
    module: str, needs_pandas: bool
) -> None:
    result = run_without_pandas(f"import isitright.packs.data.{module}; print('imported')")
    assert (result.returncode != 0) is needs_pandas, result.stderr[-300:]
