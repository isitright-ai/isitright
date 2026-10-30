import sqlite3
from pathlib import Path

import pytest

from isitright import CheckConfig, check
from isitright.core.evidence import DivergenceStatus
from isitright.core.replay import load_artifact
from isitright.packs.sql import replay_artifact, replay_report
from isitright.packs.sql.constraints_file import ConstraintInputError, load_constraint_schema
from isitright.packs.sql.reports import write_case_report
from isitright.packs.sql.validation import (
    CandidateStateView,
    ValidatorResult,
    ValidatorStatus,
)


def _logistics_database(path: Path) -> Path:
    sql = Path("tests/fixtures/proposals/synthetic_logistics.sql").read_text(encoding="utf-8")
    with sqlite3.connect(path) as connection:
        connection.executescript(sql)
    return path


def _constraints() -> Path:
    return Path("tests/fixtures/proposals/constraints.yaml")


def test_boundary_search_finds_domain_validated_counterexample(tmp_path: Path) -> None:
    database = _logistics_database(tmp_path / "logistics.sqlite")
    arguments = {
        "database": database,
        "reference_sql": "SELECT shipment_id FROM shipments WHERE package_count > 10",
        "candidate_sql": "SELECT shipment_id FROM shipments WHERE package_count >= 10",
        "constraints_file": _constraints(),
        "config": CheckConfig(seed=42),
    }
    result = check(**arguments)
    repeated = check(**arguments)

    assert result.original_state["outputs_match"] is True
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert "DOMAIN_VALIDATED" in result.validity.tiers
    (finding,) = result.findings
    assert finding.divergence["generator"] == "boundary"
    assert finding.minimization["complete"] is True
    assert result.search.attempts >= 1
    assert result.search.valid_candidates >= 1
    assert "boundary" in result.search.families_run
    assert "json-schema:" in " ".join(result.checked_rules)
    assert repeated.search == result.search
    assert repeated.findings == result.findings
    # The report names its replay artifact and command once it is written.
    write_case_report(result, tmp_path / "out")
    written = load_artifact(tmp_path / "out" / "replay.json")
    assert written.pack == "sql" and written.expected["disagrees"] is True


def test_null_search_finds_count_divergence(tmp_path: Path) -> None:
    result = check(
        database=_logistics_database(tmp_path / "logistics.sqlite"),
        reference_sql="SELECT COUNT(*) FROM shipments WHERE status = 'queued'",
        candidate_sql="SELECT COUNT(tracking_code) FROM shipments WHERE status = 'queued'",
        constraints_file=_constraints(),
        config=CheckConfig(seed=7),
    )

    assert result.original_state["outputs_match"] is True
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    (finding,) = result.findings
    assert finding.divergence["generator"] == "missing"  # the 0.1 name was "null"
    assert finding.divergence["candidate_state"]["shipments"]


def test_sum_of_differences_dogfood_is_minimized_and_replayed(tmp_path: Path) -> None:
    database = tmp_path / "tribute.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE tribute (
                tribute_id INTEGER PRIMARY KEY,
                amount_owed REAL CHECK (amount_owed >= 0),
                amount_collected REAL CHECK (amount_collected >= 0)
            );
            INSERT INTO tribute VALUES (1, 10, 3);
            """
        )

    result = check(
        database=database,
        reference_sql="SELECT SUM(amount_owed - amount_collected) FROM tribute",
        candidate_sql="SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute",
        config=CheckConfig(seed=0),
    )

    assert result.original_state["outputs_match"] is True
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    (finding,) = result.findings
    assert finding.divergence["generator"] == "missing"
    assert len(finding.divergence["candidate_state"]["tribute"]) == 2
    assert finding.minimization["rows_after"] <= 3
    write_case_report(result, tmp_path / "artifacts")
    artifact = load_artifact(tmp_path / "artifacts" / "replay.json")
    assert replay_artifact(artifact)["reproduced"] is True
    assert replay_report(result)["reproduced"] is True


def test_empty_table_synthesis_creates_complete_row_and_fk_parent(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE parent (
                parent_id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE CHECK (code IN ('ok'))
            );
            CREATE TABLE child (
                child_id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(parent_id),
                amount INTEGER NOT NULL CHECK (amount >= 0),
                label TEXT NOT NULL DEFAULT 'seed'
            );
            """
        )
    constraints = tmp_path / "constraints.yaml"
    constraints.write_text(
        """
$schema: https://json-schema.org/draft/2020-12/schema
type: object
required: [parent, child]
properties:
  parent:
    type: array
    items:
      type: object
      required: [parent_id, code]
      properties:
        parent_id: {type: integer, minimum: 1}
        code: {type: string, enum: [ok]}
  child:
    type: array
    items:
      type: object
      required: [child_id, parent_id, amount, label]
      properties:
        child_id: {type: integer, minimum: 1}
        parent_id: {type: integer, minimum: 1}
        amount: {type: integer, minimum: 0}
        label: {type: string, minLength: 1}
""".lstrip(),
        encoding="utf-8",
    )

    result = check(
        database=database,
        reference_sql="SELECT child_id FROM child WHERE amount > 10",
        candidate_sql="SELECT child_id FROM child WHERE amount >= 10",
        constraints_file=constraints,
    )

    assert result.original_state["outputs_match"] is True
    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert "DOMAIN_VALIDATED" in result.validity.tiers
    (finding,) = result.findings
    assert finding.divergence["generator"] == "boundary"
    state = finding.divergence["candidate_state"]
    assert len(state["parent"]) == 1 and len(state["child"]) == 1
    parent_row, child_row = state["parent"][0], state["child"][0]
    assert parent_row["code"] == "ok"
    assert child_row["parent_id"] == parent_row["parent_id"]
    assert child_row["label"] == "seed"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM child").fetchone() == (0,)


def test_empty_table_null_synthesis_can_create_two_row_counterexample(
    tmp_path: Path,
) -> None:
    database = tmp_path / "empty-tribute.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE tribute (
                tribute_id INTEGER PRIMARY KEY,
                amount_owed REAL CHECK (amount_owed >= 0),
                amount_collected REAL CHECK (amount_collected >= 0)
            )
            """
        )

    result = check(
        database=database,
        reference_sql="SELECT SUM(amount_owed - amount_collected) FROM tribute",
        candidate_sql="SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute",
    )

    assert result.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    (finding,) = result.findings
    # The 0.1 shared generator labeled this state "aggregation"; the family is now "missing".
    assert finding.divergence["generator"] == "missing"
    assert len(finding.divergence["candidate_state"]["tribute"]) == 2


@pytest.mark.parametrize(
    ("reference_sql", "candidate_sql", "families"),
    [
        ("SELECT zone FROM hubs", "SELECT DISTINCT zone FROM hubs", {"duplicate"}),
        (
            "SELECT h.code, c.name FROM hubs h LEFT JOIN couriers c ON c.hub_id=h.hub_id",
            "SELECT h.code, c.name FROM hubs h JOIN couriers c ON c.hub_id=h.hub_id",
            {"duplicate", "empty", "dangling", "missing", "boundary"},
        ),
    ],
)
def test_structural_mutators_find_counterexamples(
    tmp_path: Path, reference_sql: str, candidate_sql: str, families: set[str]
) -> None:
    result = check(
        database=_logistics_database(tmp_path / "structural.sqlite"),
        reference_sql=reference_sql,
        candidate_sql=candidate_sql,
        constraints_file=_constraints(),
    )
    assert result.original_state["outputs_match"] is True
    (finding,) = result.findings
    # The 0.1 "join" family is no longer a fixed string: a parent without children comes from
    # the generic duplicate, empty, dangling and missing families.
    assert finding.divergence["generator"].split("+")[-1] in families


@pytest.mark.parametrize(
    ("sql", "family"),
    [
        ("SELECT shipment_id FROM shipments WHERE status = 'queued'", "boundary"),
        ("SELECT SUM(package_count) FROM shipments", "missing"),
    ],
)
def test_applicable_mutator_families_are_accounted(tmp_path: Path, sql: str, family: str) -> None:
    result = check(
        database=_logistics_database(tmp_path / f"{family}.sqlite"),
        reference_sql=sql,
        candidate_sql=sql,
        constraints_file=_constraints(),
    )
    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert family in result.search.families_run
    assert family not in result.search.families_skipped


def test_native_window_query_reports_bounded_agreement(tmp_path: Path) -> None:
    sql = (
        "SELECT shipment_id, "
        "ROW_NUMBER() OVER (PARTITION BY hub_id ORDER BY package_count) "
        "FROM shipments"
    )
    result = check(
        database=_logistics_database(tmp_path / "window.sqlite"),
        reference_sql=sql,
        candidate_sql=sql,
        constraints_file=_constraints(),
    )

    assert result.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert "DOMAIN_VALIDATED" in result.validity.tiers
    assert result.original_state["outputs_match"] is True
    assert result.errors == []
    assert result.findings == []
    assert "not evidence of equivalence" in result.headline


def test_domain_constraints_reject_generated_boundaries(tmp_path: Path) -> None:
    result = check(
        database=_logistics_database(tmp_path / "domain.sqlite"),
        reference_sql="SELECT shipment_id FROM shipments WHERE package_count > 10001",
        candidate_sql="SELECT shipment_id FROM shipments WHERE package_count >= 10001",
        constraints_file=_constraints(),
    )
    assert result.findings == []
    assert result.search.rejected["domain_constraint"] >= 1


class IndeterminateValidator:
    @property
    def name(self) -> str:
        return "indeterminate-example"

    def __call__(self, state: CandidateStateView) -> ValidatorResult:
        assert state.engine == "sqlite"
        return ValidatorResult(
            validator_name=self.name,
            status=ValidatorStatus.INDETERMINATE,
            checked_rules=["example"],
        )


def test_indeterminate_validator_rejects_candidates(tmp_path: Path) -> None:
    result = check(
        database=_logistics_database(tmp_path / "validator.sqlite"),
        reference_sql="SELECT SUM(package_count) FROM shipments",
        candidate_sql="SELECT SUM(package_count) FROM shipments",
        validator=IndeterminateValidator(),
    )
    assert result.validity.status == "INDETERMINATE"
    assert result.search.rejected["validation_indeterminate"] >= 1
    assert "indeterminate-example" in " ".join(result.unused_rules)


def test_invalid_constraint_documents_are_input_errors(tmp_path: Path) -> None:
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("hello", encoding="utf-8")
    with pytest.raises(ConstraintInputError, match="JSON Schema object"):
        load_constraint_schema(scalar)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("type: definitely-not-a-json-schema-type", encoding="utf-8")
    with pytest.raises(ConstraintInputError, match="invalid JSON Schema"):
        load_constraint_schema(invalid)
