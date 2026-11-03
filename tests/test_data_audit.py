"""The frozen audit end to end on a small synthetic task (no benchmark data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from isitright.core.evidence import AuditReport, DivergenceStatus
from isitright.packs.data.audit import AuditConfig, AuditInputError, DataAudit
from isitright.packs.data.host import UntrustedCodeError
from isitright.packs.data.reports import (
    build_report,
    export_eval_cases,
    replay_artifact,
    write_report,
)
from isitright.packs.data.task import TaskError, load_task
from tests.data_factories import CORRECT, DROPNA_FORGOTTEN, make_task, program

CONFIG = AuditConfig(attempts=80, trust_code=True, reuse=20, timeout_seconds=20.0)
SCHEMA = Path(__file__).parents[1] / "schemas" / "report-0.6.schema.json"


@pytest.fixture(scope="module")
def audit(tmp_path_factory: pytest.TempPathFactory):
    task = load_task(make_task(tmp_path_factory.mktemp("task")))
    with DataAudit(task, CONFIG) as value:
        yield value


def test_a_correct_program_has_no_counterexample_within_the_budget(audit: DataAudit) -> None:
    case = audit.check_frozen(program(CORRECT, "correct"))
    assert case.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert case.subject_kind == "FROZEN_ARTIFACT" and case.search.executed > 10
    assert "Not found within budget" in case.headline
    assert case.comparison_policy["numbers"]["basis"].startswith("question asks for 2")
    assert case.execution_fidelity.found_on == "NATIVE_ISOLATED"
    assert case.extensions["data"]["host"]["isolation"] == "process reused for 20 runs"


@pytest.fixture(scope="module")
def mistaken(audit: DataAudit):
    return audit.check_frozen(program(DROPNA_FORGOTTEN, "dropna_forgotten"))


def test_a_mistaken_program_is_found_minimized_and_scoped_to_the_program(mistaken) -> None:
    assert mistaken.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    finding = mistaken.findings[0]
    assert finding.minimization["rows_after"] <= 3
    assert finding.divergence["scope"].startswith("this program on this world")
    assert finding.divergence["gold_answer"] != finding.divergence["program_answer"]
    assert finding.divergence["reproduces"] is True
    assert "DOMAIN_VALIDATED" in finding.validity.tiers
    assert finding.fidelity.found_on == "NATIVE_ISOLATED" and finding.fidelity.verified_on is None
    assert (
        finding.oracles[0].kind == "REFERENCE_PROGRAM" and finding.oracles[0].outcome == "NOT_MET"
    )
    assert finding.world_diff and finding.mutation_path
    assert set(finding.divergence["data_files"]) == {"orders.csv"}


def test_the_replay_artifact_reproduces_the_finding_from_the_concrete_world(
    audit: DataAudit, mistaken, tmp_path: Path
) -> None:
    artifact = audit.artifacts[mistaken.findings[0].finding_id]
    result = replay_artifact(artifact, trust_code=True)
    assert result.reproduced, result.details
    assert artifact.inputs["program_sha256"] and artifact.world["state"]["collections"]


def test_the_report_validates_against_the_schema_and_exports_an_eval_case(
    audit: DataAudit, mistaken, tmp_path: Path
) -> None:
    report = build_report([mistaken], 1.0)
    write_report(report, tmp_path / "out", audit.artifacts)
    payload = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(payload)
    assert payload["schema_version"] == "0.6"
    assert (tmp_path / "out" / payload["cases"][0]["findings"][0]["replay"]["artifact"]).is_file()
    cases = export_eval_cases(AuditReport.model_validate(payload), tmp_path / "eval")
    directory = tmp_path / "eval" / cases[0].case_id
    assert (directory / "orders.csv").is_file() and (directory / "gold.py").is_file()
    assert (directory / "question.txt").read_text(encoding="utf-8").startswith("What is the mean")
    assert "expected_answer" in cases[0].expectation
    assert "not a statement about an agent" in cases[0].expectation["scope"]


def test_a_program_that_already_disagrees_on_the_original_data_is_inconclusive(
    audit: DataAudit,
) -> None:
    case = audit.check_frozen(program(CORRECT.replace(".mean()", ".median()"), "median"))
    assert case.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert case.errors[0]["code"] == "BASELINE_DISAGREES" and not case.findings


def test_a_nondeterministic_program_is_inconclusive_not_scored(audit: DataAudit) -> None:
    code = "import random\nprint(f'@north_mean[{random.random():.2f}]')"
    case = audit.check_frozen(program(code, "random"))
    assert case.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert case.errors[0]["code"] == "NONDETERMINISTIC"
    assert any("random" in f for f in case.extensions["data"]["program_flags"])


def test_a_program_that_cannot_be_replayed_is_unsupported_with_the_reason(audit: DataAudit) -> None:
    network = audit.check_frozen(program("import requests\nrequests.get('http://x')", "net"))
    assert network.divergence_status is DivergenceStatus.UNSUPPORTED
    assert "network" in network.errors[0]["message"]
    elsewhere = audit.check_frozen(program("import pandas as pd\npd.read_csv('other.csv')", "file"))
    assert elsewhere.divergence_status is DivergenceStatus.UNSUPPORTED
    crash = audit.check_frozen(program("raise RuntimeError('x')", "crash"))
    assert crash.divergence_status is DivergenceStatus.UNSUPPORTED
    assert crash.errors[0]["code"] == "BASELINE_RUN"
    assert crash.search.executed == 0


def test_a_narrative_answer_cannot_be_judged(audit: DataAudit) -> None:
    case = audit.check_frozen(
        program("print('The north region looks higher than the rest.')", "text")
    )
    assert case.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert (
        case.errors[0]["code"] == "CANNOT_JUDGE" or case.errors[0]["code"] == "BASELINE_DISAGREES"
    )


def test_nothing_runs_without_trust_code(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path / "t"))
    with (
        DataAudit(task, AuditConfig(attempts=5)) as untrusted,
        pytest.raises(UntrustedCodeError),
    ):
        untrusted.check_frozen(program(CORRECT))


def test_a_task_directory_is_checked(tmp_path: Path) -> None:
    with pytest.raises(TaskError, match=r"task\.yaml"):
        load_task(tmp_path)
    directory = make_task(tmp_path / "t")
    (directory / "data" / "orders.csv").unlink()
    with pytest.raises(TaskError, match="not found"):
        load_task(directory)


def test_a_table_the_mapper_cannot_hold_is_an_input_error(tmp_path: Path) -> None:
    directory = make_task(tmp_path / "t")
    (directory / "data" / "orders.csv").write_text("a,a\n1,2\n", encoding="utf-8")
    with pytest.raises(AuditInputError):
        DataAudit(load_task(directory), AuditConfig(trust_code=True))
