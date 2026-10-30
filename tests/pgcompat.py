"""Thin wrappers that keep the PostgreSQL acceptance tests close to their 0.2 shape."""

from typing import Any

from isitright import check, check_suite
from isitright.core.evidence import AuditReport, CaseReport
from isitright.packs.sql import replay_report


def check_postgres(
    *, ddl: str, reference_sql: str, candidate_sql: str, engine: str = "postgres", **kwargs: Any
) -> CaseReport:
    return check(
        engine=engine,  # type: ignore[arg-type]
        ddl=ddl,
        reference_sql=reference_sql,
        candidate_sql=candidate_sql,
        **kwargs,
    )


def check_postgres_suite(*, ddl: str, cases: list[Any], engine: str = "postgres") -> AuditReport:
    return check_suite(engine=engine, ddl=ddl, cases=cases)  # type: ignore[arg-type]


def replay_postgres(report: CaseReport) -> dict[str, Any]:
    return replay_report(report)
