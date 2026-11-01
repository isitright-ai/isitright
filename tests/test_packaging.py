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
    assert all(not item.startswith("/.release-") for item in sdist_includes)
    assert isitright.__version__ == "0.5.1"
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
    assert set(extras["all"]) == (
        set(extras["postgres"]) | set(extras["duckdb"]) | set(extras["mcp"])
    )
