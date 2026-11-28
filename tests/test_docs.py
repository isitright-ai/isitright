"""The documentation's links and anchors resolve, and every page is reachable.

Checks every markdown link in ``docs/`` and ``README.md`` (outside code blocks): a relative link
needs its file and, with ``#anchor``, a heading that produces it; a link to ``docs.isitright.ai``
is read as a path in ``docs/``. Every page appears in the navigation of ``zensical.toml`` (the
about and index pages included), and every ``llms.txt`` link names a page. Anchors use the slug rule
of the toc extension: lower case, punctuation removed, spaces as hyphens.

Proposed fixture: pending owner review.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
SITE = "https://docs.isitright.ai/"


def slug(heading: str) -> str:
    text = re.sub(r"`|\*", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text).strip("-")


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    out = {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", text, re.M)}
    return out


def target_of(link: str, source: Path) -> tuple[Path | None, str]:
    """The file a link points at (None for an external or in-page link) and its anchor."""
    base, _, fragment = link.partition("#")
    if link.startswith(SITE):
        rel = base[len(SITE) :].strip("/")
        for candidate in (DOCS / f"{rel}.md", DOCS / rel / "index.md", DOCS / rel):
            if rel and candidate.is_file():
                return candidate, fragment
        return (DOCS / "index.md" if not rel else DOCS / f"{rel}.md"), fragment
    if re.match(r"[a-z]+:", link):
        return None, fragment
    if not base:
        return source, fragment
    return (source.parent / base).resolve(), fragment


PAGES = sorted([*DOCS.rglob("*.md"), ROOT / "README.md", ROOT / "CONTRIBUTING.md"])


def test_the_slug_rule_matches_the_headings_the_pages_link_to() -> None:
    assert slug("Emulation and its fidelity") == "emulation-and-its-fidelity"
    assert slug("Uniqueness without a key") == "uniqueness-without-a-key"
    assert slug("`isitright research check CORPUS`") == "isitright-research-check-corpus"
    assert slug("L2: support of a claim") == "l2-support-of-a-claim"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_link_and_anchor_resolves(page: Path) -> None:
    text = FENCE.sub("", page.read_text(encoding="utf-8"))
    broken = []
    for match in LINK.finditer(text):
        link = match.group(1)
        if link.startswith(("http://", "https://")) and not link.startswith(SITE):
            continue
        if link.startswith(("mailto:", "#")) and not link.startswith("#"):
            continue
        target, fragment = target_of(link, page)
        if target is None:
            continue
        if not target.is_file():
            if target.suffix == ".md" or link.startswith(SITE):
                broken.append(f"{link}: no such page")
            continue
        if fragment and target.suffix == ".md" and fragment not in anchors(target):
            broken.append(f"{link}: no heading makes the anchor #{fragment}")
    assert not broken, f"{page.relative_to(ROOT)}:\n  " + "\n  ".join(broken)


def nav_pages() -> set[str]:
    config = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, list):
            for entry in item:
                walk(entry)
        elif isinstance(item, dict):
            for value in item.values():
                walk(value)

    walk(config["project"]["nav"])
    return found


def test_every_page_is_in_the_navigation() -> None:
    pages = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    assert pages - nav_pages() == set(), "pages missing from zensical.toml"
    assert nav_pages() - pages == set(), "navigation entries without a page"


def test_every_llms_txt_link_names_a_page() -> None:
    text = (DOCS / "llms.txt").read_text(encoding="utf-8")
    for link in re.findall(r"\((https://docs\.isitright\.ai/[^)]*)\)", text):
        target, fragment = target_of(link, DOCS / "llms.txt")
        assert target is not None and target.is_file(), link
        if fragment:
            assert fragment in anchors(target), link


def test_a_broken_link_is_reported(tmp_path: Path) -> None:
    page = tmp_path / "a.md"
    page.write_text("# A\n\nSee [b](b.md) and [c](a.md#nowhere).\n", encoding="utf-8")
    target, _ = target_of("b.md", page)
    assert target is not None and not target.is_file()
    assert target_of("a.md#nowhere", page)[1] == "nowhere" and "nowhere" not in anchors(page)
