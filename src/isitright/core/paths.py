"""Join a base directory and a name that came from a report, and refuse any escape.

A report is an input file that anyone can write. A name or a path read from one (a data file key,
a run directory, a replay artifact) must never reach outside the directory the command was
pointed at, whatever the platform that wrote the report or the one that reads it.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafePathError(ValueError):
    """A path taken from a report would leave its base directory."""


_PLAIN = re.compile(r"[A-Za-z0-9_@%+=:,./\\-]+")


def quote_for_command(text: str) -> str:
    """A path or argument for a command line a person will paste: double quotes only when needed
    (they work in POSIX shells, cmd and PowerShell alike)."""
    if _PLAIN.fullmatch(text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def command_path(path: Path) -> str:
    """The absolute location of ``path``, quoted for a printed command that must work from any
    working directory."""
    return quote_for_command(str(path.resolve()))


def contained_path(base: Path, name: str, *, what: str = "path") -> Path:
    """Return ``base / name`` after checking that it cannot leave ``base``.

    Refused: an empty name, a NUL byte, an absolute path, a drive letter or UNC prefix, any ``..``
    component, and a name whose resolved location (symbolic links included) is outside the
    resolved base. Both ``/`` and ``\\`` count as separators on every platform, so a report written
    on Windows is checked the same way on Linux. Nothing is created or read.
    """
    if not isinstance(name, str) or not name:
        raise UnsafePathError(f"unsafe {what}: {name!r} is not a non-empty string")
    if "\0" in name:
        raise UnsafePathError(f"unsafe {what}: {name!r} contains a NUL byte")
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        raise UnsafePathError(f"unsafe {what}: {name!r} is absolute or names a drive")
    parts = [part for part in name.replace("\\", "/").split("/") if part]
    if not parts or any(part == ".." for part in parts):
        raise UnsafePathError(f"unsafe {what}: {name!r} leaves its directory")
    if any(":" in part for part in parts):
        raise UnsafePathError(f"unsafe {what}: {name!r} names a drive or an NTFS stream")
    if any(part == "." or part.endswith((".", " ")) for part in parts):
        raise UnsafePathError(
            f"unsafe {what}: {name!r} is not a plain file name "
            "(a '.' component, or a name ending in a dot or a space)"
        )
    target = base.joinpath(*parts)
    resolved_base = base.resolve()
    resolved = target.resolve()
    if resolved == resolved_base:
        raise UnsafePathError(f"unsafe {what}: {name!r} names the directory itself")
    if not resolved.is_relative_to(resolved_base):
        raise UnsafePathError(f"unsafe {what}: {name!r} resolves outside {base}")
    return target
