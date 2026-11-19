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
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = [
        m.group(1)
        for m in re.finditer(r"^## (\S+)(.*)$", text, re.MULTILINE)
        if "Unreleased" not in m.group(2)
    ]
    assert released and released[0] == isitright.__version__


def test_the_version_is_the_hotfix_release() -> None:
    assert isitright.__version__ == "0.8.1"
