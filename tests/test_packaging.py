import ast
import importlib.metadata
import re
import tomllib
from pathlib import Path

import isitright


def test_package_metadata_and_runtime_contract() -> None:
    with Path("pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    project = pyproject["project"]
    assert project["requires-python"] == ">=3.11"
    assert project["dynamic"] == ["version"]
    assert project["scripts"] == {"isitright": "isitright.cli:app"}
    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/isitright/__about__.py"
    sdist_includes = set(pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    assert "/src" in sdist_includes
    assert "/tests" in sdist_includes
    assert "/tools/release.py" in sdist_includes  # tests/test_release.py runs it
    assert all(not item.startswith("/.release-") for item in sdist_includes)
    assert isitright.__version__ == importlib.metadata.version("isitright")
    assert any(item.startswith("hypothesis") for item in project["dependencies"])
    extras = project["optional-dependencies"]
    assert not any(
        dependency.startswith(("duckdb", "psycopg", "embedded-postgres"))
        for dependency in project["dependencies"]
    )
    assert any(item.startswith("embedded-postgres") for item in extras["postgres"])
    assert not any(item.startswith("duckdb") for item in extras["postgres"])
    assert extras["duckdb"] == ["duckdb>=1.5,<2"]
    assert extras["mcp"] == ["mcp>=2.3,<3"]
    # psutil drives the data host's memory watchdog on Linux and macOS (0.9)
    assert extras["data"] == ["pandas>=2.2,<4", "psutil>=5.9,<8"]
    assert set(extras["all"]) == (
        set(extras["postgres"])
        | set(extras["duckdb"])
        | set(extras["mcp"])
        | set(extras["data"])
        | set(extras["data-schema"])
        | set(extras["parquet"])
    )


VERSION_LITERAL = re.compile(r"\d+\.\d+\.\d+")
# Files that may not hold the package version: it is written in __about__.py only, and every other
# place reads it (tools/release.py changes __about__.py and the changelog heading, nothing else).
VERSION_FREE = ("src", "tests", "docs", "tools", ".github", "examples")
VERSION_FREE_FILES = ("README.md", "CONTRIBUTING.md", "pyproject.toml", "zensical.toml")


def test_the_version_tests_hold_no_version_literal() -> None:
    """A literal version in the CLI or packaging test would have to change with every release."""
    for name in ("tests/test_cli.py", "tests/test_packaging.py"):
        tree = ast.parse(Path(name).read_text(encoding="utf-8"))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and VERSION_LITERAL.search(node.value)
        ]
        assert literals == [], f"{name} holds a version literal: {literals}"


def test_the_version_is_written_in_one_source_file() -> None:
    """Also the bare X.Y.Z of a development version, so a page that would name the release is
    caught while the version is still X.Y.Z.devN, not on the day of the release."""
    base = re.match(r"\d+\.\d+\.\d+", isitright.__version__)
    assert base is not None
    version = re.compile(rf"(?<![\d.]){re.escape(base.group())}(?!\d)")
    paths = [Path(name) for name in VERSION_FREE_FILES]
    for top in VERSION_FREE:
        paths.extend(p for p in Path(top).rglob("*") if p.is_file())
    holding = []
    for path in paths:
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".parquet", ".sqlite", ".db"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # the release script's tests use version numbers as inputs, not as the package version
        if version.search(text) and path.as_posix() != "tests/test_release.py":
            holding.append(path.as_posix())
    assert holding == ["src/isitright/__about__.py"]
