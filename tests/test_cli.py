import re
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from isitright.cli import EXIT_INVALID_INPUT, EXIT_POLICY_TRIGGERED, app
from isitright.core.evidence import DivergenceStatus, FailOn, policy_triggered
from tests.factories import make_case

runner = CliRunner()
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BOX_DRAWING_RE = re.compile(r"[\u2500-\u257f]")


@pytest.mark.parametrize(
    "command",
    [["--help"], ["sql", "--help"], ["sql", "check", "--help"], ["sql", "suite", "--help"]],
)
def test_help_surfaces_are_available(command: list[str]) -> None:
    result = runner.invoke(app, command)
    assert result.exit_code == 0
    assert "Usage" in result.output


@pytest.mark.parametrize("command", [["sql", "check", "--help"], ["sql", "suite", "--help"]])
def test_commands_document_report_format(command: list[str]) -> None:
    result = runner.invoke(app, command)
    output = ANSI_ESCAPE_RE.sub("", result.output)

    assert result.exit_code == 0
    assert "--format" in output
    assert "json" in output
    assert "markdown" in output


@pytest.mark.parametrize("command", [["sql", "check", "--help"], ["sql", "suite", "--help"]])
def test_commands_explain_ordering_policy(command: list[str]) -> None:
    result = runner.invoke(app, command)
    output = " ".join(BOX_DRAWING_RE.sub(" ", ANSI_ESCAPE_RE.sub("", result.output)).split())

    assert result.exit_code == 0
    assert "--ordering" in output
    assert "auto requires order" in output
    assert "reference query has a" in output
    assert "top-level ORDER BY" in output
    assert "ordered always requires order" in output
    assert "unordered always ignores order" in output


def test_version_is_available() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "isitright 0.4.0"


def test_invalid_fail_on_uses_reserved_input_exit_code(tmp_path: Path) -> None:
    paths = []
    for filename in ("db.sqlite", "gold.sql", "candidate.sql"):
        path = tmp_path / filename
        path.write_text("SELECT 1", encoding="utf-8")
        paths.append(path)
    result = runner.invoke(
        app,
        [
            "sql",
            "check",
            "--database",
            str(paths[0]),
            "--reference",
            str(paths[1]),
            "--candidate",
            str(paths[2]),
            "--fail-on",
            "invented",
        ],
    )
    assert result.exit_code == EXIT_INVALID_INPUT


def test_check_writes_stage_one_reports(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
        connection.execute("INSERT INTO item VALUES (1)")
    reference = tmp_path / "gold.sql"
    candidate = tmp_path / "candidate.sql"
    reference.write_text("SELECT value FROM item", encoding="utf-8")
    candidate.write_text("SELECT value FROM item", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    result = runner.invoke(
        app,
        [
            "sql",
            "check",
            "--database",
            str(database),
            "--reference",
            str(reference),
            "--candidate",
            str(candidate),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0
    assert "Queries agree on the original database" in result.output
    assert (output_dir / "case_report.json").is_file()
    assert (output_dir / "case_report.md").is_file()


def test_check_maps_invalid_database_to_input_exit_code(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    database.write_text("not sqlite", encoding="utf-8")
    reference = tmp_path / "gold.sql"
    reference.write_text("SELECT 1", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "sql",
            "check",
            "--database",
            str(database),
            "--reference",
            str(reference),
            "--candidate",
            str(reference),
        ],
    )
    assert result.exit_code == EXIT_INVALID_INPUT
    assert "could not open SQLite database" in result.output


def test_suite_rejects_a_non_database_input(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    cases = tmp_path / "cases.jsonl"
    database.write_text("not sqlite", encoding="utf-8")
    cases.write_text("", encoding="utf-8")
    result = runner.invoke(
        app,
        ["sql", "suite", "--database", str(database), "--cases", str(cases)],
    )
    assert result.exit_code == EXIT_INVALID_INPUT
    assert "could not open SQLite database" in result.output


def test_fail_on_policy_matching_is_explicit() -> None:
    domain = ("STRUCTURAL", "DOMAIN_VALIDATED")
    found = DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert not policy_triggered(make_case("a", found, domain), FailOn.NONE)
    assert not policy_triggered(
        make_case("b", DivergenceStatus.NOT_FOUND_WITHIN_BUDGET, domain), FailOn.ANY_COUNTEREXAMPLE
    )
    assert not policy_triggered(
        make_case("c", found, ("STRUCTURAL",)), FailOn.DOMAIN_COUNTEREXAMPLE
    )
    assert policy_triggered(make_case("d", found, domain), FailOn.DOMAIN_COUNTEREXAMPLE)
    assert policy_triggered(make_case("e", found, ("STRUCTURAL",)), FailOn.ANY_COUNTEREXAMPLE)


def test_an_emulated_unverified_finding_never_fails_ci_by_default() -> None:
    emulated = make_case(
        "x",
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
        ("STRUCTURAL", "DOMAIN_VALIDATED"),
        execution_fidelity={"found_on": "EMULATED", "engine": "duckdb"},
    )
    assert not policy_triggered(emulated, FailOn.ANY_COUNTEREXAMPLE)


def test_suite_cli_writes_reports(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"case_id":"q1","reference_sql":"SELECT value FROM item",'
        '"candidate_sql":"SELECT value FROM item"}\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "suite"

    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--max-attempts",
            "1",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert result.exit_code != EXIT_POLICY_TRIGGERED
    assert ". [1/1]" in result.output
    assert "1 case | 1 agreement | 0 counterexamples | 0 inconclusive | 0 unsupported" in (
        result.output
    )
    assert f"Reports: {output_dir}" in result.output
    assert "Wrote" not in result.output
    assert (output_dir / "suite_report.json").is_file()
    assert (output_dir / "suite_report.md").is_file()


def test_suite_cli_lists_only_cases_needing_review_by_default(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"case_id":"q-agree","reference_sql":"SELECT 1",'
        '"candidate_sql":"SELECT 1"}\n'
        '{"case_id":"q-diff","reference_sql":"SELECT 1",'
        '"candidate_sql":"SELECT 2"}\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "suite"

    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--max-attempts",
            "1",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "C. [2/2]" in result.output
    assert "Review:" in result.output
    assert "C q-diff" in result.output
    assert "counterexample | schema-valid | original-state" in result.output
    assert "q-agree" not in result.output


def test_suite_cli_verbose_lists_every_case_and_artifact(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"case_id":"q1","reference_sql":"SELECT 1","candidate_sql":"SELECT 1"}\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "suite"

    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--max-attempts",
            "1",
            "--output-dir",
            str(output_dir),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert "Cases:" in result.output
    assert ". q1" in result.output
    assert "agreement on tested states" in result.output
    assert "Artifacts:" in result.output
    assert f"Wrote {output_dir / 'suite_report.json'}" in result.output


def test_suite_cli_quiet_shows_only_totals_and_report_directory(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"case_id":"q1","reference_sql":"SELECT 1","candidate_sql":"SELECT 1"}\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "suite"

    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--max-attempts",
            "1",
            "--output-dir",
            str(output_dir),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    assert "1 case | 1 agreement | 0 counterexamples | 0 inconclusive | 0 unsupported" in (
        result.output
    )
    assert f"Reports: {output_dir}" in result.output
    assert "Legend:" not in result.output
    assert "[1/1]" not in result.output
    assert "Cases:" not in result.output
    assert "Review:" not in result.output
    assert "Wrote" not in result.output


def test_suite_cli_rejects_quiet_and_verbose_together(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value INTEGER)")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "sql",
            "suite",
            "--database",
            str(database),
            "--cases",
            str(cases),
            "--quiet",
            "--verbose",
        ],
    )

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "--verbose and --quiet cannot be used together" in ANSI_ESCAPE_RE.sub("", result.output)
