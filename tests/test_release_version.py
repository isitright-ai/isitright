"""The top changelog heading is the package version.

The version is in ``src/isitright/__about__.py`` only
(``tests/test_packaging.py`` checks that no other file holds it); ``tools/release.py`` changes it
and the top changelog heading together.
"""

from __future__ import annotations

import re
from pathlib import Path

import isitright

ROOT = Path(__file__).parents[1]


def test_the_top_changelog_heading_is_the_package_version() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(r"^## (\S+)", text, re.MULTILINE)
    assert heading is not None and heading.group(1) == isitright.__version__
