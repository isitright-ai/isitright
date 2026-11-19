"""Reports and replay artifacts written by 0.8.0 still load, replay and export."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.evidence import AuditReport

OLD = Path(__file__).parent / "fixtures" / "reports" / "research-0.8.0"
runner = CliRunner()


def test_a_0_8_report_loads_with_its_old_schema_version() -> None:
    report = AuditReport.model_validate_json((OLD / "report.json").read_text(encoding="utf-8"))
    assert report.schema_version == "0.8" and report.pack == "research"
    findings = report.cases[0].findings
    assert len(findings) == 5
    assert all(f.stability is None or f.stability.sequential is None for f in findings)


def test_a_replay_artifact_written_by_0_8_0_still_replays() -> None:
    for number in range(1, 6):
        result = runner.invoke(app, ["research", "replay", str(OLD / f"{number}.replay.json")])
        assert result.exit_code == 0, result.output
        assert "Reproduced." in result.output, result.output


def test_a_0_8_report_exports_its_cases(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["research", "export", str(OLD / "report.json"), "--output", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "5 eval case(s) exported" in result.output
    first = json.loads((tmp_path / "1.eval-case.json").read_text(encoding="utf-8"))
    assert first["pack"] == "research"
