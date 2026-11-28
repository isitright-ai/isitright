"""tools/release.py on temporary copies of the two files it changes, in a fresh git repository.

The real repository is never written: each test copies ``__about__.py`` and ``CHANGELOG.md`` into
``tmp_path``, commits them, and runs the script there.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release.py"

if shutil.which("git") is None:  # pragma: no cover - git is present wherever the suite runs
    pytest.skip("git is needed", allow_module_level=True)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_script"] = module
    spec.loader.exec_module(module)
    return module


release = _load()

CHANGELOG = (
    "# Changelog\n\nAll notable changes are documented here.\n\n"
    "## {top}\n\nSomething new.\n\n## 0.8.0 - Research agents\n\nOlder.\n"
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def make_repo(
    tmp_path: Path, version: str, top: str, *, crlf: bool = False, tags: tuple[str, ...] = ()
) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "isitright").mkdir(parents=True)
    about = '"""Package metadata kept independent from runtime imports."""\n\n'
    about += f'__version__ = "{version}"\n'
    log = CHANGELOG.format(top=top)
    if crlf:
        about, log = about.replace("\n", "\r\n"), log.replace("\n", "\r\n")
    (root / "src" / "isitright" / "__about__.py").write_bytes(about.encode())
    (root / "CHANGELOG.md").write_bytes(log.encode())
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "start")
    for tag in tags:
        _git(root, "tag", tag)
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        name: (root / name).read_bytes() for name in ("src/isitright/__about__.py", "CHANGELOG.md")
    }


def run(root: Path, *args: str, capsys: Any) -> tuple[int, str, str]:
    code = release.main([*args, "--root", str(root)])
    out, err = capsys.readouterr()
    return code, out, err


def test_a_dry_run_shows_exactly_the_lines_it_would_change_and_writes_nothing(
    tmp_path: Path, capsys: Any
) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - Hardening")
    before = snapshot(root)
    code, out, err = run(root, "0.9.0", "--dry-run", capsys=capsys)
    assert (code, err) == (0, "")
    changed = [line for line in out.splitlines() if line[:1] in "+-" and line[:3] not in "+++---"]
    assert changed == [
        '-__version__ = "0.9.0.dev0"',
        '+__version__ = "0.9.0"',
        "-## 0.9.0.dev0 - Hardening",
        "+## 0.9.0 - Hardening",
    ]
    assert "--- a/src/isitright/__about__.py" in out and "+++ b/CHANGELOG.md" in out
    assert out.rstrip().endswith("dry run: nothing written")
    assert snapshot(root) == before


def test_a_release_renames_the_top_heading_and_changes_nothing_else(
    tmp_path: Path, capsys: Any
) -> None:
    root = make_repo(tmp_path, "0.9.0.dev3", "0.9.0.dev3 - Hardening")
    assert run(root, "0.9.0", capsys=capsys)[0] == 0
    assert '__version__ = "0.9.0"\n' in (root / "src/isitright/__about__.py").read_text()
    log = (root / "CHANGELOG.md").read_text()
    assert log == CHANGELOG.format(top="0.9.0 - Hardening")
    diff = _git(root, "diff", "--numstat")
    assert sorted(diff.split("\n")[:-1]) == [
        "1\t1\tCHANGELOG.md",
        "1\t1\tsrc/isitright/__about__.py",
    ]


def test_starting_a_version_adds_a_heading_and_keeps_crlf_line_endings(
    tmp_path: Path, capsys: Any
) -> None:
    root = make_repo(tmp_path, "0.8.1", "0.8.1 - Fixes", crlf=True)
    assert run(root, "0.9.0.dev0", "--title", "Hardening", capsys=capsys)[0] == 0
    log = (root / "CHANGELOG.md").read_bytes()
    assert b"\r\n\r\n## 0.9.0.dev0 - Hardening\r\n\r\n## 0.8.1 - Fixes\r\n" in log
    assert b"\n" not in log.replace(b"\r\n", b"")
    about = (root / "src/isitright/__about__.py").read_bytes()
    assert about.endswith(b'__version__ = "0.9.0.dev0"\r\n')


def test_a_later_development_version_renames_the_heading_and_keeps_its_title(
    tmp_path: Path, capsys: Any
) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - Hardening")
    assert run(root, "0.9.0.dev1", capsys=capsys)[0] == 0
    assert "## 0.9.0.dev1 - Hardening\n" in (root / "CHANGELOG.md").read_text()


@pytest.mark.parametrize(
    ("current", "top", "asked", "message"),
    [
        ("0.9.0.dev0", "0.9.0.dev0 - H", "0.9", "'0.9' is not a version of the form X.Y.Z"),
        ("0.9.0.dev0", "0.9.0.dev0 - H", "0.9.0rc1", "is not a version of the form X.Y.Z"),
        ("0.9.0", "0.9.0 - H", "0.9.0", "0.9.0 is not greater than the current version 0.9.0"),
        ("0.9.0", "0.9.0 - H", "0.8.9", "0.8.9 is not greater than the current version 0.9.0"),
        ("0.9.0", "0.9.0 - H", "0.9.0.dev7", "0.9.0.dev7 is not greater than the current"),
        ("0.9.0.dev2", "0.9.0.dev2 - H", "0.9.0.dev1", "is not greater than the current"),
        ("0.9.0.dev0", "0.8.0 - H", "0.9.0", "needs a top changelog heading 0.9.0.devN"),
        ("0.9.0.dev0", "0.9.0 - H", "0.9.0", "the top heading is 0.9.0"),
        ("0.9.0.dev0", "0.9.0.dev0 - H", "0.10.0", "needs a top changelog heading 0.10.0.dev"),
        ("0.8.0", "0.8.0 - H", "0.9.0.dev0", "adds a changelog heading: give it a --title"),
    ],
)
def test_refusals_name_the_reason_and_write_nothing(
    tmp_path: Path,
    capsys: Any,
    current: str,
    top: str,
    asked: str,
    message: str,
) -> None:
    root = make_repo(tmp_path, current, top)
    before = snapshot(root)
    code, out, err = run(root, asked, capsys=capsys)
    assert code == 2
    assert err.startswith("release.py: refused: ") and message in err, err
    assert out == ""
    assert snapshot(root) == before


@pytest.mark.parametrize("tag", ["v0.9.0", "0.9.0"])
def test_a_version_that_already_has_a_tag_is_refused(tmp_path: Path, capsys: Any, tag: str) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - H", tags=(tag,))
    code, _, err = run(root, "0.9.0", "--dry-run", capsys=capsys)
    assert code == 2 and f"0.9.0 already has a tag: {tag}" in err


def test_a_dirty_tree_is_refused_even_for_a_dry_run(tmp_path: Path, capsys: Any) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - H")
    (root / "CHANGELOG.md").write_text("edited\n")
    code, _, err = run(root, "0.9.0", "--dry-run", capsys=capsys)
    assert code == 2 and "the working tree has uncommitted changes" in err
    assert (root / "CHANGELOG.md").read_text() == "edited\n"


def test_an_untracked_file_does_not_block_a_release(tmp_path: Path, capsys: Any) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - H")
    (root / "notes.txt").write_text("scratch\n")
    assert run(root, "0.9.0", capsys=capsys)[0] == 0


def test_a_missing_version_line_is_a_refusal_not_a_crash(tmp_path: Path, capsys: Any) -> None:
    root = make_repo(tmp_path, "0.9.0.dev0", "0.9.0.dev0 - H")
    (root / "src/isitright/__about__.py").write_text("VERSION = '1'\n")
    _git(root, "commit", "-qam", "break")
    code, _, err = run(root, "0.9.0", capsys=capsys)
    assert code == 2 and 'has no line __version__ = "..."' in err


def test_the_command_line_exits_two_on_a_refusal(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "0.9.0", "0.9.0 - H")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "0.9.0", "--root", str(root)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "release.py: refused: 0.9.0 is not greater" in completed.stderr


def test_versions_order_development_releases_before_the_release() -> None:
    parse = release.Version.parse
    assert parse("0.9.0.dev0") < parse("0.9.0.dev10") < parse("0.9.0") < parse("0.10.0.dev0")
    assert str(parse("1.2.3.dev4")) == "1.2.3.dev4" and str(parse("1.2.3")) == "1.2.3"


def test_the_repository_itself_is_at_a_version_the_script_can_read() -> None:
    assert str(release.current_version(ROOT)) == __import__("isitright").__version__
