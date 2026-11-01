"""SQL pack: audit text-to-SQL programs by perturbing the database they run on.

`check` compares a reference and a candidate query on SQLite (a database file or DDL), PostgreSQL
(native, from DDL) or DuckDB (emulated PostgreSQL, from DDL). `check_suite` does the same for a
JSONL suite. Both return report models of schema 0.5. See https://docs.isitright.ai/sql/supported-sql/.
"""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Any

from isitright.core.evidence import AuditReport, CaseReport
from isitright.packs.sql.audit import Engine, InputError, SqlAudit, SqlCase
from isitright.packs.sql.constraints_file import ConstraintInputError, load_constraint_schema
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    CheckConfig,
    ColumnComparisonPolicy,
    EffectiveOrdering,
    FloatComparisonMode,
    OrderingPolicy,
    SuiteCase,
)
from isitright.packs.sql.replaying import (
    export_eval_cases,
    replay_artifact,
    replay_report,
    rerun_eval_case,
)
from isitright.packs.sql.suite import SuiteInputError, load_suite_cases
from isitright.packs.sql.validation import (
    CandidateStateValidator,
    CandidateStateView,
    ValidationFinding,
    ValidatorResult,
    ValidatorStatus,
)


def _constraints(
    constraints: dict[str, Any] | None, constraints_file: str | PathLike[str] | None
) -> dict[str, Any] | None:
    if constraints_file is None:
        return constraints
    try:
        return load_constraint_schema(Path(constraints_file))
    except ConstraintInputError as error:
        raise InputError(str(error)) from error


def check(
    *,
    reference_sql: str,
    candidate_sql: str,
    engine: Engine = "sqlite",
    database: str | PathLike[str] | None = None,
    ddl: str | None = None,
    question: str | None = None,
    case_id: str | None = None,
    constraints: dict[str, Any] | None = None,
    constraints_file: str | PathLike[str] | None = None,
    config: CheckConfig | None = None,
    validator: CandidateStateValidator | None = None,
    verify_native: bool | None = None,
    _server: tuple[Any, str] | None = None,
    _progress: Any = None,
) -> CaseReport:
    """Compare two read-only queries on perturbed worlds; the user's data is never modified."""
    with SqlAudit(
        engine=engine,
        database=database,
        ddl=ddl,
        domain_schema=_constraints(constraints, constraints_file),
        validator=validator,
        verify_native=verify_native,
        _server=_server,
    ) as audit:
        case = SqlCase(reference_sql, candidate_sql, case_id, question)
        return audit.check(case, config, _progress)


def check_suite(
    *,
    cases: str | PathLike[str] | list[SuiteCase],
    engine: Engine = "sqlite",
    database: str | PathLike[str] | None = None,
    ddl: str | None = None,
    constraints: dict[str, Any] | None = None,
    constraints_file: str | PathLike[str] | None = None,
    config: CheckConfig | None = None,
    validator: CandidateStateValidator | None = None,
    verify_native: bool | None = None,
    _progress: Any = None,
) -> AuditReport:
    """Analyze a JSONL suite (or a list of `SuiteCase`), isolating per-case failures."""
    audit = SqlAudit(
        engine=engine,
        database=database,
        ddl=ddl,
        domain_schema=_constraints(constraints, constraints_file),
        validator=validator,
        verify_native=verify_native,
    )
    try:
        items = load_suite_cases(Path(cases)) if isinstance(cases, str | PathLike) else list(cases)
    except SuiteInputError as error:
        raise InputError(str(error)) from error
    ids = [case.case_id for case in items]
    if len(ids) != len(set(ids)):
        raise InputError("case IDs must be unique")
    if not items:  # nothing to run: no server is started and nothing is claimed
        return audit.check_suite([], config, _progress)
    with audit:
        return audit.check_suite(items, config, _progress)


__all__ = [
    "CandidateStateValidator",
    "CandidateStateView",
    "CanonicalValue",
    "CanonicalValueKind",
    "CheckConfig",
    "ColumnComparisonPolicy",
    "EffectiveOrdering",
    "FloatComparisonMode",
    "InputError",
    "OrderingPolicy",
    "SqlAudit",
    "SqlInputError",
    "SuiteCase",
    "ValidationFinding",
    "ValidatorResult",
    "ValidatorStatus",
    "check",
    "check_suite",
    "export_eval_cases",
    "replay_artifact",
    "replay_report",
    "rerun_eval_case",
]
