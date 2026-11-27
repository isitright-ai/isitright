"""P7: every place the repository records the release version agrees with the package.

The package version lives in ``src/isitright/__about__.py``. The docs copyright line, ``llms.txt``
and the top changelog heading must name the same version, so a bump that misses one fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import isitright

ROOT = Path(__file__).parents[1]


def test_the_docs_copyright_line_names_the_package_version() -> None:
    text = (ROOT / "zensical.toml").read_text(encoding="utf-8")
    assert f"Documentation for isitright {isitright.__version__}." in text


def test_llms_txt_names_the_package_version() -> None:
    text = (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8")
    assert f"version {isitright.__version__}." in text


def test_the_top_changelog_heading_is_the_package_version() -> None:
    """A release names the newest released heading. A development version names the release it
    leads to, whose heading is the newest one and still marked unreleased."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [
        (m.group(1), "Unreleased" in m.group(2))
        for m in re.finditer(r"^## (\S+)(.*)$", text, re.MULTILINE)
    ]
    release, development, _ = isitright.__version__.partition(".dev")
    if development:
        assert headings[0] == (release, True)
    else:
        assert next(v for v, unreleased in headings if not unreleased) == release


def test_the_version_is_the_development_version() -> None:
    assert isitright.__version__ == "0.9.0.dev0"
