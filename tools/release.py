"""Set the package version and the top changelog heading, the two places a release changes.

The version lives in ``src/isitright/__about__.py`` only; everything else reads it from there (the
package metadata through hatch, the CLI's ``--version``, the tests). The changelog keeps one heading
per release, newest first, written ``## X.Y.Z.devN - Title`` while a release is being developed and
``## X.Y.Z - Title`` once it is released.

    python tools/release.py X.Y.Z                        # release: rename the top heading
    python tools/release.py X.Y.Z.dev0 --title Title     # start the next version: add a heading
    python tools/release.py X.Y.Z --dry-run              # print the changes, write nothing

Refused, with nothing written: a version that is not ``X.Y.Z`` or ``X.Y.Z.devN``; a version that is
not greater than the current one; a version that already has a tag (``vX.Y.Z`` or ``X.Y.Z``); a
working tree with uncommitted changes; a release whose top changelog heading is not a development
heading of the same ``X.Y.Z``; a new development version without ``--title``.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ABOUT = Path("src/isitright/__about__.py")
CHANGELOG = Path("CHANGELOG.md")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$")
ABOUT_RE = re.compile(r'^__version__ = "([^"]+)"(?=\r?$)', re.MULTILINE)
HEADING_RE = re.compile(r"^## (\S+)(?: - ([^\r\n]*))?(?=\r?$)", re.MULTILINE)


class ReleaseError(Exception):
    """A refusal: the message says what is wrong; nothing has been written."""


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int
    final: bool
    """A release sorts after every development version of the same X.Y.Z."""
    dev: int

    @classmethod
    def parse(cls, text: str) -> Version:
        match = VERSION_RE.match(text)
        if match is None:
            raise ReleaseError(f"{text!r} is not a version of the form X.Y.Z or X.Y.Z.devN")
        major, minor, patch, dev = match.groups()
        return cls(int(major), int(minor), int(patch), dev is None, int(dev or 0))

    @property
    def base(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __str__(self) -> str:
        return self.base if self.final else f"{self.base}.dev{self.dev}"


@dataclass(frozen=True)
class Change:
    path: Path
    before: str
    after: str

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{self.path.as_posix()}",
                tofile=f"b/{self.path.as_posix()}",
                n=0,
            )
        )


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseError(f"git {' '.join(args)} failed: {error}") from error
    return completed.stdout


def _read(root: Path, path: Path) -> str:
    try:
        # newline="" keeps each file's own line endings (the repository has both)
        with (root / path).open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError as error:
        raise ReleaseError(f"cannot read {path.as_posix()}: {error}") from error


def current_version(root: Path) -> Version:
    match = ABOUT_RE.search(_read(root, ABOUT))
    if match is None:
        raise ReleaseError(f'{ABOUT.as_posix()} has no line __version__ = "..."')
    return Version.parse(match.group(1))


def plan(root: Path, version: str, title: str | None = None) -> list[Change]:
    """The changes that set ``version``, or a ``ReleaseError``. Reads only; writes nothing."""
    new = Version.parse(version)
    old = current_version(root)
    if new <= old:
        raise ReleaseError(f"{new} is not greater than the current version {old}")
    tags = set(_git(root, "tag", "--list", f"v{new}", str(new)).split())
    if tags:
        raise ReleaseError(f"{new} already has a tag: {', '.join(sorted(tags))}")
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ReleaseError("the working tree has uncommitted changes; commit or stash them first")

    about = _read(root, ABOUT)
    changes = [
        Change(ABOUT, about, ABOUT_RE.sub(f'__version__ = "{new}"', about, count=1)),
    ]

    log = _read(root, CHANGELOG)
    heading = HEADING_RE.search(log)
    if heading is None:
        raise ReleaseError(f"{CHANGELOG.as_posix()} has no '## ' heading")
    top_text, top_title = heading.group(1), heading.group(2)
    try:
        top = Version.parse(top_text)
    except ReleaseError:
        raise ReleaseError(
            f"the top heading of {CHANGELOG.as_posix()} names {top_text!r}, not a version"
        ) from None
    suffix = f" - {top_title}" if top_title else ""
    if new.final:
        if top.final or top.base != new.base:
            raise ReleaseError(
                f"releasing {new} needs a top changelog heading {new}.devN; "
                f"the top heading is {top_text}"
            )
        if title:
            suffix = f" - {title}"
        renamed = f"## {new}{suffix}"
        updated = log[: heading.start()] + renamed + log[heading.end() :]
    elif not top.final and top.base == new.base:
        # a later development version of the same release: rename its heading
        if title:
            suffix = f" - {title}"
        updated = log[: heading.start()] + f"## {new}{suffix}" + log[heading.end() :]
    else:
        if not title:
            raise ReleaseError(f"starting {new} adds a changelog heading: give it a --title")
        eol = "\r\n" if log[heading.end() : heading.end() + 2] == "\r\n" else "\n"
        added = f"## {new} - {title}{eol}{eol}"
        updated = log[: heading.start()] + added + log[heading.start() :]
    changes.append(Change(CHANGELOG, log, updated))
    return changes


def apply(root: Path, changes: list[Change]) -> None:
    for change in changes:
        with (root / change.path).open("w", encoding="utf-8", newline="") as handle:
            handle.write(change.after)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tools/release.py", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("version", help="X.Y.Z to release, or X.Y.Z.devN to start or continue one")
    parser.add_argument("--title", help="the changelog heading's title (needed to start a version)")
    parser.add_argument("--dry-run", action="store_true", help="print the changes; write nothing")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="the repository (default: the one this script is in)",
    )
    args = parser.parse_args(argv)
    try:
        changes = plan(args.root, args.version, args.title)
    except ReleaseError as error:
        print(f"release.py: refused: {error}", file=sys.stderr)
        return 2
    for change in changes:
        sys.stdout.write(change.diff())
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    apply(args.root, changes)
    print(f"set the version to {Version.parse(args.version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
