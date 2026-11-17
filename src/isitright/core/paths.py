"""Join a base directory and a name that came from a report, and refuse any escape.

A report is an input file that anyone can write. A name or a path read from one (a data file key,
a run directory, a replay artifact) must never reach outside the directory the command was
pointed at, whatever the platform that wrote the report or the one that reads it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafePathError(ValueError):
    """A path taken from a report would leave its base directory."""


def replay_placeholder(output_dir: Path | str, filename: str) -> str:
    """Where a printed replay command names a report file, as a placeholder in angle brackets.

    A report is moved (a CI artifact is downloaded), so nothing it says may name the directory it
    was written to, and the command cannot hold a location that is true on the reader's machine.
    The reader replaces the placeholder with the file's location. The placeholder is the path the
    user gave for the output directory when that was relative (so it also reads as the location
    from where the audit ran), and the bare file name otherwise: never an absolute path.
    """
    given = PureWindowsPath(str(output_dir))
    local = not (given.is_absolute() or given.drive or given.root or ".." in given.parts)
    shown = str(Path(output_dir) / filename) if local else filename
    return f"<{shown}>"


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
