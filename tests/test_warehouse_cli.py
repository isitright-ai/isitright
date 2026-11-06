"""The `sql check` and `sql suite` commands with a warehouse dialect."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("duckdb")

from isitright.cli import app

runner = CliRunner()

# Proposed fixture: pending owner review (constructed schema and queries, written by Claude).
DDL = "CREATE TABLE `proj.shop.items` (id INT64 NOT NULL, tags ARRAY<INT64>, name STRING)"
LEFT = "SELECT t.id, tag FROM `proj.shop.items` AS t LEFT JOIN UNNEST(t.tags) AS tag"
CROSS = "SELECT t.id, tag FROM `proj.shop.items` AS t CROSS JOIN UNNEST(t.tags) AS tag"


def _files(tmp_path: Path, reference: str = LEFT, candidate: str = CROSS) -> list[str]:
    (tmp_path / "schema.sql").write_text(DDL, encoding="utf-8")
    (tmp_path / "ref.sql").write_text(reference, encoding="utf-8")
    (tmp_path / "cand.sql").write_text(candidate, encoding="utf-8")
    return [
        "--schema",
        str(tmp_path / "schema.sql"),
        "--reference",
        str(tmp_path / "ref.sql"),
        "--candidate",
        str(tmp_path / "cand.sql"),
    ]


def test_check_with_a_bigquery_dialect_finds_the_lead_example(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app, ["sql", "check", "--dialect", "bigquery", *_files(tmp_path), "--output-dir", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "emulating BigQuery" in result.output
    assert "not been confirmed on BigQuery (use --confirm)" in result.output
    report = json.loads((out / "case_report.json").read_text(encoding="utf-8"))["cases"][0]
    assert report["extensions"]["sql"]["target_dialect"] == "bigquery"
    assert (out / "counterexample.sql").read_text(encoding="utf-8").startswith("-- Generated")


def test_param_fills_a_placeholder_and_a_missing_one_is_exit_code_two(tmp_path: Path) -> None:
    files = _files(tmp_path, "SELECT id FROM t WHERE ds = '<DS>'", "SELECT id FROM t")
    (tmp_path / "schema.sql").write_text("CREATE TABLE t (id bigint, ds varchar)", encoding="utf-8")
    base = ["sql", "check", "--dialect", "presto", *files, "--max-attempts", "20"]
    bad = runner.invoke(app, [*base, "--output-dir", str(tmp_path / "a")])
    assert bad.exit_code == 2 and "UNFILLED_PLACEHOLDER: <DS>" in bad.output
    good = runner.invoke(
        app, [*base, "--param", "DS=2020-01-01", "--output-dir", str(tmp_path / "b")]
    )
    assert good.exit_code in (0, 1), good.output
    report = json.loads((tmp_path / "b" / "case_report.json").read_text(encoding="utf-8"))["cases"][
        0
    ]
    assert report["extensions"]["sql"]["template"]["params"] == {"DS": "2020-01-01"}


def test_a_dialect_and_an_engine_that_do_not_go_together_are_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["sql", "check", "--dialect", "bigquery", "--engine", "postgres", *_files(tmp_path)],
    )
    assert result.exit_code == 2 and "cannot run on engine" in result.output


def test_confirm_connection_needs_a_function_and_trust(tmp_path: Path) -> None:
    base = ["sql", "check", "--dialect", "bigquery", "--confirm", "connection", *_files(tmp_path)]
    no_function = runner.invoke(app, [*base, "--output-dir", str(tmp_path / "a")])
    assert no_function.exit_code == 2 and "--connection" in no_function.output
    untrusted = runner.invoke(
        app,
        [*base, "--connection", "tests.test_warehouse_hosts:fake_run", "--output-dir", "x"],
    )
    assert untrusted.exit_code == 2 and "--trust-code" in untrusted.output


def test_confirm_with_a_trusted_connection_function_verifies_the_finding(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "sql",
            "check",
            "--dialect",
            "bigquery",
            "--confirm",
            "connection",
            "--connection",
            "tests.test_warehouse_hosts:fake_run",
            "--trust-code",
            *_files(tmp_path),
            "--output-dir",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Confirmed on connection with the state inlined." in result.output
    report = json.loads((out / "case_report.json").read_text(encoding="utf-8"))["cases"][0]
    assert report["findings"][0]["fidelity"]["verified_on"] == "NATIVE_INLINE"


def test_existing_engine_invocations_keep_their_meaning(tmp_path: Path) -> None:
    (tmp_path / "s.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY)", encoding="utf-8")
    (tmp_path / "r.sql").write_text("SELECT id FROM t", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "sql",
            "check",
            "--engine",
            "duckdb",
            "--schema",
            str(tmp_path / "s.sql"),
            "--reference",
            str(tmp_path / "r.sql"),
            "--candidate",
            str(tmp_path / "r.sql"),
            "--max-attempts",
            "5",
            "--no-verify-native",
            "--output-dir",
            str(tmp_path / "o"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "emulating PostgreSQL" in result.output
    report = json.loads((tmp_path / "o" / "case_report.json").read_text(encoding="utf-8"))["cases"][
        0
    ]
    assert report["extensions"]["sql"]["target_dialect"] == "postgres"
