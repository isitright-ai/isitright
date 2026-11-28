"""The data and warehouse quick starts print what they say they print.

Each ``console`` block that starts with ``isitright`` and is followed directly by a ``text``
block is run on the repository's example files, in order, in one temporary directory; every
line of the text block must be a line the command printed, in the same order (a block may leave
lines out, but may not invent or reorder them). Paths are compared with forward slashes and
non-ASCII characters as ``?``, so the pages read the same on every platform. A page that drifts from
the code fails here.

Proposed fixture: pending owner review (the pages and their examples are written by Claude).
"""

from __future__ import annotations

import itertools
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)


def pairs(page: Path) -> list[tuple[str, list[str]]]:
    """(command, expected output lines) for each console block followed directly by a text block."""
    text = page.read_text(encoding="utf-8")
    blocks = [(m.group(1), m.group(2), m.start(), m.end()) for m in FENCE.finditer(text)]
    out = []
    for (kind, body, _, end), (next_kind, next_body, next_start, _) in itertools.pairwise(blocks):
        if kind != "console" or next_kind != "text" or text[end:next_start].strip():
            continue
        command = " ".join(line.rstrip("\\").strip() for line in body.strip().splitlines())
        if command.startswith("isitright "):
            out.append((command, [ln.rstrip() for ln in next_body.strip().splitlines()]))
    return out


def normal(line: str) -> str:
    line = line.replace("\\", "/").rstrip()
    return "".join(c if ord(c) < 128 else "?" for c in line)


def run(command: str, cwd: Path) -> list[str]:
    argv = [
        str(ROOT / part) if part.startswith("examples/") else part
        for part in shlex.split(command, posix=True)[1:]
    ]
    done = subprocess.run(
        [sys.executable, "-c", "from isitright.cli import app; app()", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    assert done.returncode in (0, 1), (command, done.stdout, done.stderr)
    return [normal(line) for line in (done.stdout + done.stderr).splitlines()]


def check_page(page: Path, tmp_path: Path) -> int:
    checked = 0
    for command, expected in pairs(page):
        printed = run(command, tmp_path)
        position = 0
        for line in map(normal, expected):
            try:
                position = printed.index(line, position) + 1
            except ValueError:
                pytest.fail(
                    f"{page.name}: the page shows a line the command did not print, or out of "
                    f"order:\n  {line}\nafter: {command}\nprinted:\n" + "\n".join(printed)
                )
        checked += 1
    return checked


def test_the_data_quick_start_prints_what_the_page_shows(tmp_path: Path) -> None:
    assert check_page(ROOT / "docs" / "get-started" / "data.md", tmp_path) == 3


def test_the_warehouse_quick_start_prints_what_the_page_shows(tmp_path: Path) -> None:
    assert check_page(ROOT / "docs" / "get-started" / "warehouses.md", tmp_path) == 7


def test_the_pairs_are_found_and_a_drifted_line_is_caught(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "```console\nisitright --version\n```\n\n```text\nisitright 9.9.9\n```\n", encoding="utf-8"
    )
    assert pairs(page) == [("isitright --version", ["isitright 9.9.9"])]
    with pytest.raises(pytest.fail.Exception, match="the page shows a line the command did not"):
        check_page(page, tmp_path)


def test_a_console_block_with_prose_between_it_and_the_output_is_not_a_pair(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "```console\nisitright --version\n```\n\nSome words.\n\n```text\nx\n```\n", encoding="utf-8"
    )
    assert pairs(page) == []
