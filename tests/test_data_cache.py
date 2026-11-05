"""The run cache and resumable audits: an interrupted audit keeps finished work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")

from typer.testing import CliRunner

from isitright.cli import app
from isitright.core.evidence import DivergenceStatus
from isitright.packs.data.audit import AuditConfig, DataAudit
from isitright.packs.data.cache import RunCache, run_key
from isitright.packs.data.host import RunResult
from isitright.packs.data.programs import write_programs
from isitright.packs.data.task import load_task
from tests.data_factories import CORRECT, DROPNA_FORGOTTEN, make_task, program

runner = CliRunner()


def result(answer: str = "1", status: str = "ok") -> RunResult:
    return RunResult(status, stdout=answer, versions={"pandas": "x"}, seconds=0.5)


def test_runs_are_restored_from_the_file(tmp_path: Path) -> None:
    path = tmp_path / "t" / "gold.jsonl"
    first = RunCache(path, "host-a")
    first.put("k1", result("1"))
    first.put("k2", RunResult("error", error="boom", violations=["v"]))
    second = RunCache(path, "host-a")
    assert second.restored == 2
    assert second.get("k1") == result("1")
    assert second.get("k2") == RunResult("error", error="boom", violations=["v"])
    assert second.get("missing") is None


def test_a_torn_last_line_is_dropped_and_later_records_are_intact(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    RunCache(path, "h").put("k1", result("1"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "k2", "run": {"status": "ok", "stdo')  # a crash mid-write
    reopened = RunCache(path, "h")
    assert reopened.restored == 1 and reopened.get("k2") is None
    reopened.put("k3", result("3"))
    final = RunCache(path, "h")
    assert final.restored == 2 and final.get("k3") == result("3")


def test_a_cache_made_under_another_host_configuration_is_not_used(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    RunCache(path, "timeout 30").put("k1", result())
    assert RunCache(path, "timeout 120").restored == 0


@pytest.mark.parametrize("status", ["timeout", "memory"])
def test_runs_that_depend_on_machine_load_are_not_stored(tmp_path: Path, status: str) -> None:
    cache = RunCache(tmp_path / "p.jsonl", "h")
    cache.put("k", result(status=status))
    assert cache.get("k") is None and RunCache(tmp_path / "p.jsonl", "h").restored == 0


def test_an_answer_that_is_not_plain_json_is_simply_not_stored(tmp_path: Path) -> None:
    cache = RunCache(tmp_path / "p.jsonl", "h")
    cache.put("k", RunResult("ok", final_answer=object(), has_final_answer=True))
    assert cache.get("k") is None


def test_the_key_depends_on_the_code_and_the_world() -> None:
    assert run_key("a", "w1") != run_key("b", "w1")
    assert run_key("a", "w1") != run_key("a", "w2")
    assert run_key("a", "w1") == run_key("a", "w1")


def counting(audit: DataAudit) -> list[int]:
    calls = [0]
    original = audit.host.run

    def run(code: str, state: Any) -> RunResult:
        calls[0] += 1
        return original(code, state)

    audit.host.run = run  # type: ignore[method-assign]
    return calls


def test_a_second_audit_repeats_no_run_that_the_first_finished(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path / "orders"))
    config = AuditConfig(
        attempts=40, trust_code=True, reuse=20, timeout_seconds=20.0, cache_dir=tmp_path / "cache"
    )
    mistaken = program(DROPNA_FORGOTTEN, "mistake")
    with DataAudit(task, config) as first:
        first_calls = counting(first)
        before = first.check_frozen(mistaken)
    assert before.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert first_calls[0] > 10
    with DataAudit(task, config) as second:
        second_calls = counting(second)
        after = second.check_frozen(mistaken)
    # only the check that two runs on the original data agree is made again, on purpose
    assert second_calls[0] == 1
    assert after.divergence_status is before.divergence_status
    assert after.search.model_dump() == before.search.model_dump()
    assert after.findings[0].world_diff == before.findings[0].world_diff
    assert after.findings[0].minimization == before.findings[0].minimization
    assert after.findings[0].divergence["difference"] == before.findings[0].divergence["difference"]


def test_discarding_removes_the_files_the_audit_wrote(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path / "orders"))
    cache = tmp_path / "cache"
    config = AuditConfig(attempts=10, trust_code=True, reuse=20, cache_dir=cache)
    correct = program(CORRECT, "correct")
    with DataAudit(task, config) as audit:
        audit.check_frozen(correct)
        assert (cache / "orders" / "correct.jsonl").is_file()
        assert (cache / "orders" / "gold.jsonl").is_file()
        audit.discard_cache(correct)
        assert not (cache / "orders" / "correct.jsonl").exists()
        audit.discard_cache()
    assert not (cache / "orders").exists()


class Crash(BaseException):
    """Stands for a machine that goes away: nothing in the audit may catch it."""


def arguments(task: Path, programs: Path, out: Path, *extra: str) -> list[str]:
    return [
        "data",
        "check",
        str(task),
        "--programs",
        str(programs),
        "--output",
        str(out),
        "--trust-code",
        "--attempts",
        "30",
        "--reuse",
        "20",
        *extra,
    ]


def test_a_crashed_audit_resumes_with_the_programs_it_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(tmp_path / "orders")
    programs = tmp_path / "programs.jsonl"
    write_programs(programs, [program(CORRECT, "correct"), program(DROPNA_FORGOTTEN, "mistake")])
    out, cache = tmp_path / "out", tmp_path / "cache"
    real = DataAudit.check_frozen

    def crashing(self: DataAudit, p: Any, progress: Any = None) -> Any:
        if p.program_id == "mistake":
            raise Crash
        return real(self, p, progress)

    monkeypatch.setattr(DataAudit, "check_frozen", crashing)
    with pytest.raises(Crash):
        runner.invoke(app, arguments(task, programs, out, "--cache", str(cache)))
    assert (out / ".resume" / "units" / "orders_correct.json").is_file()
    assert not (out / "report.json").exists()

    seen: list[str] = []

    def recording(self: DataAudit, p: Any, progress: Any = None) -> Any:
        seen.append(p.program_id)
        return real(self, p, progress)

    monkeypatch.setattr(DataAudit, "check_frozen", recording)
    refused = runner.invoke(app, arguments(task, programs, out, "--cache", str(cache)))
    assert refused.exit_code == 2 and "--resume" in refused.output
    resumed = runner.invoke(app, arguments(task, programs, out, "--cache", str(cache), "--resume"))
    assert resumed.exit_code == 0, resumed.output
    assert seen == ["mistake"]
    assert "orders:correct: NOT_FOUND_WITHIN_BUDGET (kept from before)" in resumed.output
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [c["divergence_status"] for c in report["cases"]] == [
        "NOT_FOUND_WITHIN_BUDGET",
        "COUNTEREXAMPLE_FOUND",
    ]
    finding = report["cases"][1]["findings"][0]
    assert (out / finding["replay"]["artifact"]).is_file()
    assert not (out / ".resume").exists() and not cache.exists()


def test_a_resumed_audit_must_use_the_settings_of_the_interrupted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(tmp_path / "orders")
    programs = tmp_path / "programs.jsonl"
    write_programs(programs, [program(CORRECT, "correct")])
    out = tmp_path / "out"

    def crashing(self: DataAudit, p: Any, progress: Any = None) -> Any:
        raise Crash

    monkeypatch.setattr(DataAudit, "check_frozen", crashing)
    with pytest.raises(Crash):
        runner.invoke(app, arguments(task, programs, out))
    changed = arguments(task, programs, out, "--resume")
    changed[changed.index("30")] = "31"
    refused = runner.invoke(app, changed)
    assert refused.exit_code == 2 and "attempts" in refused.output
    assert not (out / "report.json").exists()


def test_a_finished_audit_cannot_be_resumed(tmp_path: Path) -> None:
    task = make_task(tmp_path / "orders")
    programs = tmp_path / "programs.jsonl"
    write_programs(programs, [program(CORRECT, "correct")])
    out = tmp_path / "out"
    assert runner.invoke(app, arguments(task, programs, out)).exit_code == 0
    again = runner.invoke(app, arguments(task, programs, out, "--resume"))
    assert again.exit_code == 2 and "nothing to resume" in again.output
