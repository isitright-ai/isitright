"""Replay and eval-case export for SQL counterexamples.

Replay starts from the concrete minimized state recorded in the report. It rebuilds the schema on
the recorded engine, loads the rows, runs both programs, and checks that both outputs and the
disagreement recur. Report-provided SQL is never executed as a fixture: only the schema DDL the
audit itself recorded is, in a fresh in-memory database.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from isitright.core.evidence import CaseReport, DivergenceStatus, EvalCase
from isitright.core.replay import ReplayArtifact, ReplayResult, replay
from isitright.core.world import State
from isitright.packs.sql.analysis import validate_read_only_query
from isitright.packs.sql.comparison import compare_results
from isitright.packs.sql.domain_validation import domain_errors
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.fixture_replay import _replay_fixture_authorizer
from isitright.packs.sql.hosts import DuckdbHost, PostgresHost, SqlHost, SqliteHost
from isitright.packs.sql.mapping import SqlModel, build_model, decode, to_database_state
from isitright.packs.sql.models import ComparisonPolicy, OrderingPolicy
from isitright.packs.sql.postgres_ddl import (
    Schema,
    _validate_domain_schema,
    parse_postgres_database_schema,
    parse_query,
)
from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.sqlite_schema import introspect_schema
from isitright.packs.sql.state import DatabaseState, TableState

REPLAY_TIMEOUT_SECONDS = 30.0
REPLAY_MAX_RESULT_ROWS = 10_000


def artifact_from_report(report: CaseReport) -> ReplayArtifact:
    """The replay artifact for a report's first finding."""
    if report.divergence_status is not DivergenceStatus.COUNTEREXAMPLE_FOUND or not report.findings:
        raise SqlInputError("case report does not contain counterexample evidence")
    finding = report.findings[0]
    sql = report.extensions.get("sql", {})
    return ReplayArtifact(
        pack="sql",
        case_id=report.case_id,
        world={"rows": finding.divergence["candidate_state"]},
        host={
            "engine": sql.get("execution_engine"),
            "schema_ddl": sql.get("schema_ddl"),
            "engine_version": report.execution_fidelity.engine,
        },
        inputs={
            "reference_sql": report.inputs["reference_sql"],
            "candidate_sql": report.inputs["candidate_sql"],
            "question": report.inputs.get("question"),
            "comparison_policy": report.comparison_policy,
            "constraints": report.inputs.get("constraints"),
            "validity_tiers": finding.validity.tiers,
        },
        expected={
            "reference_result": finding.divergence["reference_result"],
            "candidate_result": finding.divergence["candidate_result"],
            "disagrees": True,
        },
    )


def _schema(engine: str, ddl: list[str]) -> tuple[DatabaseSchema, Schema | None]:
    if engine == "sqlite":
        connection = sqlite3.connect(":memory:")
        connection.set_authorizer(_replay_fixture_authorizer)
        try:
            for statement in ddl:
                connection.execute(statement)
            connection.set_authorizer(None)  # introspection needs PRAGMAs; the DDL ran guarded
            return introspect_schema(connection), None
        except sqlite3.Error as error:
            raise SqlInputError(f"invalid recorded schema: {error}") from error
        finally:
            connection.close()
    db = parse_postgres_database_schema(ddl[0])
    return db, Schema(db)


def _state(model: SqlModel, rows: dict[str, list[dict[str, Any]]]) -> DatabaseState:
    tables = []
    for table in model.db.tables:
        columns = model.columns(table.name)
        by_name = {c.name: c for c in table.columns}
        data = tuple(
            tuple(decode(row.get(c), by_name[c]) for c in columns)
            for row in rows.get(table.name, [])
        )
        tables.append(TableState(table.name, columns, data))
    return DatabaseState(tuple(tables))


def _rerun(
    artifact: ReplayArtifact,
    *,
    timeout_seconds: float = REPLAY_TIMEOUT_SECONDS,
    max_result_rows: int = REPLAY_MAX_RESULT_ROWS,
) -> dict[str, Any]:
    host_info = artifact.host
    engine = host_info.get("engine")
    ddl = host_info.get("schema_ddl")
    if engine not in ("sqlite", "postgres", "duckdb") or not ddl:
        raise SqlInputError("unsupported report engine or missing schema")
    reference = artifact.inputs["reference_sql"]
    candidate = artifact.inputs["candidate_sql"]
    db, pg = _schema(engine, list(ddl))
    constraints = artifact.inputs.get("constraints")
    domain_validated = "DOMAIN_VALIDATED" in artifact.inputs.get("validity_tiers", [])
    if engine != "sqlite" and domain_validated and constraints is None:
        raise SqlInputError("domain-validated report lacks its constraints")
    if constraints is not None and not isinstance(constraints, dict):
        raise SqlInputError("invalid domain constraints in report")
    _validate_domain_schema(constraints)
    model = build_model(db, "sqlite" if engine == "sqlite" else "postgres")
    data = _state(model, artifact.world["rows"])
    if constraints is not None and domain_errors(data.records(), constraints):
        raise SqlInputError("replayed state violates the recorded domain constraints")
    if engine == "sqlite":
        validate_read_only_query(reference)
        validate_read_only_query(candidate)
    else:
        assert pg is not None
        parse_query(reference, pg, allow_qualified=True)
        parse_query(candidate, pg, allow_qualified=True)
    host: SqlHost
    if engine == "sqlite":
        host = SqliteHost(db)
        left, right = host.run_pair(
            data,
            reference,
            candidate,
            timeout_seconds=timeout_seconds,
            max_result_rows=max_result_rows,
        )
    elif engine == "postgres":
        assert pg is not None
        with PostgresHost(pg) as postgres:
            host = postgres
            left, right = host.run_pair(
                data,
                reference,
                candidate,
                timeout_seconds=timeout_seconds,
                max_result_rows=max_result_rows,
            )
    else:
        assert pg is not None
        host = DuckdbHost(pg)
        left, right = host.run_pair(
            data,
            reference,
            candidate,
            timeout_seconds=timeout_seconds,
            max_result_rows=max_result_rows,
        )
    try:
        policy = ComparisonPolicy.model_validate(
            {
                k: v
                for k, v in artifact.inputs.get("comparison_policy", {}).items()
                if k in ComparisonPolicy.model_fields
            }
        )
    except ValueError as error:
        raise SqlInputError("invalid ordering policy in report") from error
    ordered = (
        validate_read_only_query(reference).top_level_ordered
        if engine == "sqlite"
        else parse_query(reference, pg, allow_qualified=True).args.get("order") is not None  # type: ignore[arg-type]
    )
    if policy.ordering is OrderingPolicy.AUTO and policy.effective_ordering is None:
        policy = policy.model_copy(update={"ordering": OrderingPolicy.AUTO})
    disagrees = not compare_results(
        left, right, policy=policy, reference_has_order_by=ordered
    ).matches
    return {
        "reference_result": left.model_dump(mode="json"),
        "candidate_result": right.model_dump(mode="json"),
        "disagrees": disagrees,
        "engine_version": host.version,
        "execution_engine": engine,
    }


def replay_artifact(
    artifact: ReplayArtifact,
    *,
    timeout_seconds: float = REPLAY_TIMEOUT_SECONDS,
    max_result_rows: int = REPLAY_MAX_RESULT_ROWS,
) -> dict[str, Any]:
    """Rebuild the recorded state and compare both outputs on the recorded engine."""
    if timeout_seconds <= 0 or max_result_rows < 1:
        raise SqlInputError("budgets must be positive")
    observed: dict[str, Any] = {}

    def rerun(a: ReplayArtifact) -> dict[str, Any]:
        observed.update(_rerun(a, timeout_seconds=timeout_seconds, max_result_rows=max_result_rows))
        return observed

    result: ReplayResult = replay(artifact, rerun)
    recorded = artifact.host.get("engine_version")
    return {
        "reproduced": result.reproduced,
        "details": result.details,
        "execution_engine": observed.get("execution_engine"),
        "engine_version": observed.get("engine_version"),
        "recorded_engine_version": recorded,
        "version_matches": recorded is not None
        and str(recorded).endswith(str(observed.get("engine_version"))),
        "reference_result": observed.get("reference_result"),
        "candidate_result": observed.get("candidate_result"),
    }


def replay_report(report: CaseReport, **limits: Any) -> dict[str, Any]:
    return replay_artifact(artifact_from_report(report), **limits)


def export_eval_cases(report: CaseReport) -> list[EvalCase]:
    """Each finding as a new eval case: a fixture state, both programs and the expectation."""
    artifact = artifact_from_report(report)
    return [
        EvalCase(
            pack="sql",
            case_id=f"{report.case_id}-generated-{index + 1}",
            source_finding=finding.finding_id,
            payload={
                "engine": artifact.host["engine"],
                "schema_ddl": artifact.host["schema_ddl"],
                "state_rows": artifact.world["rows"],
                "question": artifact.inputs.get("question"),
                "reference_sql": artifact.inputs["reference_sql"],
                "candidate_sql": artifact.inputs["candidate_sql"],
                "comparison_policy": artifact.inputs["comparison_policy"],
                "constraints": artifact.inputs.get("constraints"),
                "validity_tiers": artifact.inputs["validity_tiers"],
            },
            expectation={
                "outputs_differ": True,
                "reference_result": artifact.expected["reference_result"],
                "candidate_result": artifact.expected["candidate_result"],
            },
        )
        for index, finding in enumerate(report.findings[:1])
    ]


def rerun_eval_case(case: EvalCase) -> dict[str, Any]:
    """Rerun an exported case; `reproduced` is True when the programs still disagree as recorded."""
    artifact = ReplayArtifact(
        pack="sql",
        case_id=case.case_id,
        world={"rows": case.payload["state_rows"]},
        host={"engine": case.payload["engine"], "schema_ddl": case.payload["schema_ddl"]},
        inputs={
            k: case.payload.get(k)
            for k in (
                "reference_sql",
                "candidate_sql",
                "question",
                "comparison_policy",
                "constraints",
                "validity_tiers",
            )
        },
        expected={
            "reference_result": case.expectation["reference_result"],
            "candidate_result": case.expectation["candidate_result"],
            "disagrees": case.expectation["outputs_differ"],
        },
    )
    return replay_artifact(artifact)


def state_of(model: SqlModel, data: DatabaseState) -> State:  # pragma: no cover - convenience
    from isitright.packs.sql.mapping import to_state

    return to_state(model, data)


__all__ = [
    "artifact_from_report",
    "export_eval_cases",
    "replay_artifact",
    "replay_report",
    "rerun_eval_case",
    "to_database_state",
]
