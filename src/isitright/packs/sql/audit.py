"""The SQL pack's audit: perturb the database, run two programs, compare, minimize.

One orchestration serves SQLite (seeded databases, or DDL only), PostgreSQL (DDL, native) and
DuckDB (PostgreSQL DDL, emulated). The world is an entity state; the core's families perturb it,
the core's search composes mutations to depth two, and the core's minimizer shrinks the result.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

from isitright.core.constraints import (
    Constraint,
    PythonConstraint,
    Validity,
    ValidityStatus,
)
from isitright.core.evidence import (
    AuditReport,
    CaseReport,
    DivergenceStatus,
    FidelityRecord,
    Finding,
    MutationRecord,
    OracleRecord,
    ReplayRecord,
    SearchRecord,
    ValidityRecord,
    safe_detail,
    totals_of,
)
from isitright.core.families import default_mutators
from isitright.core.minimize import minimize_world
from isitright.core.mutations import Candidate, World
from isitright.core.search import Evaluation, SearchResult, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.subjects import SubjectKind
from isitright.core.world import State, diff_states, sha256_text
from isitright.packs.sql import hints as _hints  # noqa: F401  (registers the SQL hint kinds)
from isitright.packs.sql.analysis import (
    SqlStatement,
    SqlValidationError,
    harvest_query_guidance,
    validate_read_only_query,
)
from isitright.packs.sql.comparison import ComparisonError, compare_results, resolve_ordering
from isitright.packs.sql.domain_validation import domain_errors
from isitright.packs.sql.errors import SqlInputError, StateRejected
from isitright.packs.sql.hints import hints_from_guidance
from isitright.packs.sql.hosts import DuckdbHost, PostgresHost, SqlHost, SqliteHost
from isitright.packs.sql.mapping import (
    SqlModel,
    build_model,
    fallback_base_state,
    generate_base_state,
    import_json_schema,
    import_sql_checks,
    to_database_state,
    to_state,
)
from isitright.packs.sql.models import (
    CanonicalValue,
    CanonicalValueKind,
    CheckConfig,
    ComparisonPolicy,
    QueryResult,
    SuiteCase,
)
from isitright.packs.sql.postgres_ddl import (
    Schema,
    _validate_domain_schema,
    parse_postgres_database_schema,
    parse_query,
)
from isitright.packs.sql.reproducer import postgres_reproducer, sqlite_reproducer
from isitright.packs.sql.sqlite_sandbox import (
    DatabaseInputError,
    QueryExecutionError,
    QueryResourceLimitError,
    QueryTimeoutError,
    SQLiteSandbox,
    canonicalize_sqlite_value,
)
from isitright.packs.sql.sqlite_schema import introspect_schema
from isitright.packs.sql.sqlite_state import snapshot_sqlite
from isitright.packs.sql.state import DatabaseState
from isitright.packs.sql.validation import (
    CandidateStateValidator,
    ValidatorStatus,
)

Engine = Literal["sqlite", "postgres", "duckdb"]
Progress = Callable[[str], None]


class InputError(ValueError):
    """A required input cannot be read or changed while it was being analyzed."""


class _Abort(Exception):
    """A native engine failed in a way the search cannot continue from."""


@dataclass
class SqlCase:
    """The inputs of one comparison: two programs on the audit's world."""

    reference_sql: str
    candidate_sql: str
    case_id: str | None = None
    question: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class StateView:
    """Read-only, engine-neutral view of one state for trusted validators."""

    def __init__(self, model: SqlModel, state: State, engine: str) -> None:
        self._model, self._state, self._engine = model, state, engine

    @property
    def engine(self) -> str:
        return self._engine

    def table_names(self) -> list[str]:
        return [t.name for t in self._model.db.tables]

    def rows(self, table: str) -> list[dict[str, CanonicalValue]]:
        data = to_database_state(self._model, self._state)
        state_table = next(t for t in data.tables if t.name == table)
        return [
            {c: canonical_value(v) for c, v in zip(state_table.columns, row, strict=True)}
            for row in state_table.rows
        ]


def canonical_value(value: Any) -> CanonicalValue:
    from decimal import Decimal

    if isinstance(value, Decimal):
        return CanonicalValue(kind=CanonicalValueKind.DECIMAL, value=str(value))
    if isinstance(value, bool):
        return CanonicalValue(kind=CanonicalValueKind.BOOLEAN, value=value)
    return canonicalize_sqlite_value(value)


@dataclass
class Prepared:
    engine: Engine
    model: SqlModel
    spec: WorldSpec
    base: State
    """The world mutations start from: the seed, or a generated state when the tables are empty."""
    original: State
    """The data as supplied (empty for a schema-only run); the original-state comparison uses it."""
    seeded: bool
    pg: Schema | None
    source: dict[str, Any]
    domain_schema: dict[str, Any] | None = None
    validator: CandidateStateValidator | None = None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SqlAudit(AbstractContextManager["SqlAudit"]):
    """A prepared world (schema, seed or generated base) and its host; reusable across cases."""

    def __init__(
        self,
        *,
        engine: Engine = "sqlite",
        database: str | PathLike[str] | None = None,
        ddl: str | None = None,
        domain_schema: dict[str, Any] | None = None,
        validator: CandidateStateValidator | None = None,
        _server: tuple[Any, str] | None = None,
    ) -> None:
        if engine not in ("sqlite", "postgres", "duckdb"):
            raise SqlInputError("engine must be sqlite, postgres or duckdb")
        if (database is None) == (ddl is None):
            raise SqlInputError("give exactly one of a database file or DDL")
        if database is not None and engine != "sqlite":
            raise SqlInputError("a database file is only supported for sqlite")
        self.engine: Engine = engine
        self._server = _server
        self.host: SqlHost
        self._executed: tuple[str, str] = ("", "")
        self._host_context: AbstractContextManager[Any] | None = None
        _validate_domain_schema(domain_schema)
        self.prepared = self._prepare(engine, database, ddl, domain_schema, validator)

    # --- preparation ------------------------------------------------------------------------

    def _prepare(
        self,
        engine: Engine,
        database: str | PathLike[str] | None,
        ddl: str | None,
        domain_schema: dict[str, Any] | None,
        validator: CandidateStateValidator | None,
    ) -> Prepared:
        pg: Schema | None = None
        source: dict[str, Any] = {}
        seeded = False
        if engine == "sqlite" and database is not None:
            path = _readable_file(database, "database")
            source = {"database": str(path), "database_sha256": _sha256_file(path)}
            try:
                with SQLiteSandbox(path) as sandbox:
                    assert sandbox.connection is not None and sandbox.schema is not None
                    db = sandbox.schema
                    data = snapshot_sqlite(sandbox.connection, db)
            except DatabaseInputError as error:
                raise InputError(str(error)) from error
            seeded = True
        elif engine == "sqlite":
            assert ddl is not None
            connection = sqlite3.connect(":memory:")
            try:
                connection.executescript(ddl)
                db = introspect_schema(connection)
            except sqlite3.Error as error:
                raise SqlInputError(f"invalid SQLite DDL: {error}") from error
            finally:
                connection.close()
            data = DatabaseState(())
            source = {"ddl": ddl}
        else:
            assert ddl is not None
            db = parse_postgres_database_schema(ddl)
            pg = Schema(db)
            data = DatabaseState(())
            source = {"ddl": ddl}
        dialect: Literal["sqlite", "postgres"] = "sqlite" if engine == "sqlite" else "postgres"
        model = build_model(db, dialect)
        constraints: list[Constraint] = [*model.constraints, *import_sql_checks(model)]
        python_rules: list[PythonConstraint] = []
        if domain_schema is not None:
            constraints.extend(import_json_schema(model, domain_schema))
            python_rules.append(_json_schema_rule(model, domain_schema))
        if validator is not None:
            python_rules.append(_validator_rule(model, validator, engine))
        spec = WorldSpec(
            id="sql", schema=model.schema, constraints=constraints, python_constraints=python_rules
        )
        base_data: DatabaseState | None = data
        if not any(t.rows for t in data.tables):
            base_data = generate_base_state(model, constraints)
            if base_data is None and engine == "sqlite":
                base_data = fallback_base_state(model, constraints)
            if base_data is None:
                base_data = DatabaseState(tuple(_empty_table(model, t.name) for t in db.tables))
        assert base_data is not None
        base = to_state(model, base_data)
        original = to_state(model, data) if seeded else base
        return Prepared(
            engine, model, spec, base, original, seeded, pg, source, domain_schema, validator
        )

    def __enter__(self) -> Self:
        p = self.prepared
        if self.engine == "sqlite":
            self.host = SqliteHost(p.model.db)
        elif self.engine == "postgres":
            assert p.pg is not None
            postgres = PostgresHost(p.pg, self._server)
            self._host_context = postgres
            postgres.__enter__()
            self.host = postgres
        else:
            assert p.pg is not None
            self.host = DuckdbHost(p.pg)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._host_context is not None:
            self._host_context.__exit__(exc_type, exc_value, traceback)
            self._host_context = None

    # --- one comparison ---------------------------------------------------------------------

    def check(
        self,
        case: SqlCase,
        config: CheckConfig | None = None,
        progress: Progress | None = None,
    ) -> CaseReport:
        started = time.monotonic()
        config = config or CheckConfig()
        _check_budgets(config)
        p = self.prepared
        try:
            statements = (
                self._statement(case.reference_sql),
                self._statement(case.candidate_sql),
            )
        except (SqlValidationError, SqlInputError) as error:
            if self.engine != "sqlite":
                raise SqlInputError(str(error)) from error
            return self._unsupported(case, str(error), started)
        reference_statement, candidate_statement = statements
        self._executed = (
            (
                reference_statement.expression.sql(dialect="duckdb"),
                candidate_statement.expression.sql(dialect="duckdb"),
            )
            if self.engine == "duckdb"
            else (case.reference_sql, case.candidate_sql)
        )
        policy = ComparisonPolicy(
            columns=config.column_policy,
            ordering=config.ordering_policy,
            float_mode=config.float_mode,
            float_relative_tolerance=config.float_relative_tolerance,
            float_absolute_tolerance=config.float_absolute_tolerance,
        ).model_copy(
            update={
                "effective_ordering": resolve_ordering(
                    config.ordering_policy,
                    reference_has_order_by=reference_statement.top_level_ordered,
                )
            }
        )
        guidance = harvest_query_guidance(reference_statement, candidate_statement)
        hints = hints_from_guidance(p.model, guidance)
        hints.validate(p.model.schema)
        referenced = [t for t in (x.name for x in p.model.db.tables) if t in guidance.tables]
        if p.domain_schema is not None:
            required = p.domain_schema.get("required", [])
            if isinstance(required, list):
                known = set(p.model.schema.keys())
                referenced.extend(str(n) for n in required if str(n) in known)
        if p.validator is not None:
            referenced = list(p.model.schema.keys())
        errors: list[dict[str, str]] = []
        ordered = reference_statement.top_level_ordered

        def run(state: State) -> tuple[QueryResult, QueryResult]:
            return self.host.run_pair(
                to_database_state(p.model, state),
                case.reference_sql,
                case.candidate_sql,
                timeout_seconds=config.timeout_seconds,
                max_result_rows=config.max_result_rows,
            )

        def disagrees(state: State) -> tuple[bool, QueryResult, QueryResult, str | None]:
            left, right = run(state)
            outcome = compare_results(left, right, policy=policy, reference_has_order_by=ordered)
            return (not outcome.matches, left, right, outcome.difference)

        base_world = World(p.base)
        original: dict[str, Any] = {"outputs_match": None, "note": "skipped: schema-only run"}
        original_validity = p.spec.validate(p.original)
        original_diff: tuple[QueryResult, QueryResult, str | None] | None = None
        if p.seeded:
            assert isinstance(self.host, SqliteHost)
            outputs = self.host.run_each(
                to_database_state(p.model, p.original),
                [case.reference_sql, case.candidate_sql],
                timeout_seconds=config.timeout_seconds,
                max_result_rows=config.max_result_rows,
            )
            failures = [
                (name, item)
                for name, item in zip(("reference", "candidate"), outputs, strict=True)
                if isinstance(item, QueryExecutionError)
            ]
            if failures:
                for name, failure in failures:
                    code = (
                        "QUERY_TIMEOUT"
                        if isinstance(failure, QueryTimeoutError)
                        else "QUERY_RESOURCE_LIMIT"
                        if isinstance(failure, QueryResourceLimitError)
                        else "QUERY_ERROR"
                    )
                    errors.append({"code": code, "message": str(failure), "phase": name})
                reference_ok = outputs[0] if isinstance(outputs[0], QueryResult) else None
                candidate_ok = outputs[1] if isinstance(outputs[1], QueryResult) else None
                return self._report(
                    case,
                    policy,
                    started,
                    config,
                    status=DivergenceStatus.INCONCLUSIVE,
                    validity=ValidityRecord(status="VALID", tiers=["STRUCTURAL"]),
                    headline="Original-state comparison was inconclusive: a query did not complete",
                    original={
                        "outputs_match": None,
                        "reference_result": reference_ok.model_dump(mode="json")
                        if reference_ok
                        else None,
                        "candidate_result": candidate_ok.model_dump(mode="json")
                        if candidate_ok
                        else None,
                        "note": "At least one query timed out or returned an execution error.",
                    },
                    errors=errors,
                    search_result=None,
                )
            first, second = outputs
            assert isinstance(first, QueryResult) and isinstance(second, QueryResult)
            left, right = first, second
            try:
                outcome = compare_results(
                    left, right, policy=policy, reference_has_order_by=ordered
                )
            except ComparisonError as error:
                errors.append(
                    {"code": "AMBIGUOUS_COMPARISON", "message": str(error), "phase": "comparison"}
                )
                return self._report(
                    case,
                    policy,
                    started,
                    config,
                    status=DivergenceStatus.INCONCLUSIVE,
                    validity=ValidityRecord(status="VALID", tiers=["STRUCTURAL"]),
                    headline=f"Original-state comparison was inconclusive: {safe_detail(error)}",
                    original={
                        "outputs_match": None,
                        "reference_result": left.model_dump(mode="json"),
                        "candidate_result": right.model_dump(mode="json"),
                        "note": str(error),
                    },
                    errors=errors,
                    search_result=None,
                )
            original = {
                "outputs_match": outcome.matches,
                "reference_result": left.model_dump(mode="json"),
                "candidate_result": right.model_dump(mode="json"),
                "note": outcome.difference,
            }
            if not outcome.matches:
                original_diff = (left, right, outcome.difference)
            self._assert_unchanged()

        # An original-data mismatch is a finding on the unmutated world, if it is admissible.
        if original_diff is not None and original_validity.status is ValidityStatus.VALID:
            finding = self._finding(
                case,
                World(p.original),
                p.original,
                original_validity,
                original_diff,
                referenced=referenced,
                config=config,
                disagrees=disagrees,
                generator="original_state",
                description="No generated mutation; the original database diverged.",
                base=None,
            )
            return self._report(
                case,
                policy,
                started,
                config,
                status=DivergenceStatus.COUNTEREXAMPLE_FOUND,
                validity=finding.validity,
                headline="Original-data mismatch: queries return different results",
                original=original,
                errors=errors,
                search_result=None,
                findings=[finding],
                checked=list(original_validity.checked_rules),
            )

        search_errors: list[str] = []

        def evaluate(candidate: Candidate, validity: Validity) -> Evaluation:
            try:
                differs, left, right, difference = disagrees(candidate.world.state)
            except StateRejected as error:
                search_errors.append(str(error))
                return Evaluation(
                    Verdict.REJECTED,
                    reason="sqlite_constraint" if self.engine == "sqlite" else "engine_constraint",
                )
            except QueryExecutionError as error:
                search_errors.append(str(error))
                return Evaluation(Verdict.ERROR, reason="query_error")
            except ComparisonError as error:
                search_errors.append(str(error))
                return Evaluation(Verdict.INCONCLUSIVE, reason="comparison_ambiguous")
            except Exception as error:
                if self.engine == "sqlite":
                    raise
                errors.append(
                    {
                        "code": "ENGINE_ERROR",
                        "message": f"{type(error).__name__}: {error}",
                        "phase": "search",
                    }
                )
                if progress is not None:
                    progress("error")
                raise _Abort from error
            if differs:
                return Evaluation(Verdict.DISAGREE, detail=(left, right, difference))
            return Evaluation(Verdict.AGREE)

        budget = Budget(attempts=config.max_attempts)
        try:
            if not guidance.tables and p.seeded:
                result = SearchResult(seed=config.seed, budget=budget)
                result.notes.append("neither program reads a table, so there is nothing to perturb")
            else:
                result = search(
                    p.spec,
                    base_world,
                    hints,
                    default_mutators(insert_variants=True) if guidance.tables else [],
                    evaluate,
                    budget=budget,
                    seed=config.seed,
                    depth=2,
                    progress=progress,
                    include_base=not p.seeded,
                )
        except _Abort:
            return self._report(
                case,
                policy,
                started,
                config,
                status=DivergenceStatus.INCONCLUSIVE,
                validity=ValidityRecord(status="NOT_ASSESSED"),
                headline=f"Inconclusive: {safe_detail(errors[-1]['message'])}",
                original=original,
                errors=errors,
                search_result=None,
            )
        result.errors.extend(search_errors[:10])
        base_validity = p.spec.validate(p.base)
        if not p.seeded and base_validity.status is not ValidityStatus.VALID:
            # Mutations start from a generated state the rules reject; count it, say so.
            result.reject("domain_constraint")
            result.notes.append(
                "the generated base state violates the domain rules; candidates are checked alone"
            )
        if p.seeded:
            self._assert_unchanged()
        if result.findings:
            found = result.findings[0]
            left, right, difference = found.evaluation.detail
            finding = self._finding(
                case,
                found.candidate.world,
                found.candidate.world.state,
                found.validity,
                (left, right, difference),
                referenced=referenced,
                config=config,
                disagrees=disagrees,
                generator=found.candidate.world.path[-1].family
                if len(found.candidate.world.path) == 1
                else "+".join(m.family for m in found.candidate.world.path),
                description="; ".join(m.description for m in found.candidate.world.path),
                base=p.base,
            )
            family = finding.mutation_path[-1].family if finding.mutation_path else "baseline"
            return self._report(
                case,
                policy,
                started,
                config,
                status=DivergenceStatus.COUNTEREXAMPLE_FOUND,
                validity=finding.validity,
                headline=f"Generated counterexample: queries diverge after a {family} mutation",
                original=original,
                errors=errors,
                search_result=result,
                findings=[finding],
                checked=list(found.validity.checked_rules),
            )
        admitted = result.valid
        if original_diff is not None:
            status = DivergenceStatus.INCONCLUSIVE
            headline = (
                "Original database diverges but is not admissible under configured validation; "
                "no admissible generated counterexample was found"
            )
        elif not admitted and guidance.tables:
            status = DivergenceStatus.INCONCLUSIVE
            headline = "No generated state satisfied the schema and domain constraints"
            if not errors:
                errors.append(
                    {
                        "code": "NO_ADMISSIBLE_STATE",
                        "message": "No generated state satisfied the schema and domain rules.",
                        "phase": "search",
                    }
                )
        else:
            status = DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
            headline = (
                f"No disagreement found in {result.executed} admitted generated states "
                "within the budget; this is not evidence of equivalence"
            )
            if p.seeded and original.get("outputs_match"):
                headline = (
                    f"Queries agree on the original database and {admitted} admitted generated "
                    "states within the budget; this is not evidence of equivalence"
                )
        strongest = result.strongest
        validity = (
            _validity_record(strongest)
            if strongest is not None and admitted
            else _validity_record(original_validity)
            if original_validity.status is ValidityStatus.VALID
            else ValidityRecord(
                status=(
                    "INDETERMINATE"
                    if original_validity.status is ValidityStatus.INDETERMINATE
                    else "NOT_ASSESSED"
                )
            )
        )
        return self._report(
            case,
            policy,
            started,
            config,
            status=status,
            validity=validity,
            headline=headline,
            original=original,
            errors=errors,
            search_result=result,
            checked=list(strongest.checked_rules) if strongest else [],
        )

    # --- helpers ------------------------------------------------------------------------------

    def _statement(self, sql: str) -> SqlStatement:
        if self.engine == "sqlite":
            return validate_read_only_query(sql)
        assert self.prepared.pg is not None
        tree = parse_query(sql, self.prepared.pg, allow_qualified=True)
        return SqlStatement(expression=tree, top_level_ordered=tree.args.get("order") is not None)

    def _ddl_statements(self) -> list[str]:
        p = self.prepared
        if self.engine != "sqlite":
            return [str(p.source["ddl"])]
        tables = p.model.db.tables
        return [t.ddl for t in tables] + [i for t in tables for i in t.index_ddls]

    def _assert_unchanged(self) -> None:
        source = self.prepared.source
        if (
            "database" in source
            and _sha256_file(Path(source["database"])) != source["database_sha256"]
        ):
            raise InputError("database changed while it was being analyzed")

    def _fidelity(self) -> FidelityRecord:
        return FidelityRecord(
            found_on=self.host.fidelity.value,
            verified_on=None,
            engine=f"{self.host.engine} {self.host.version}"
            if self.host.version
            else self.host.engine,
        )

    def _finding(
        self,
        case: SqlCase,
        world: World,
        state: State,
        validity: Validity,
        outputs: tuple[QueryResult, QueryResult, str | None],
        *,
        referenced: list[str],
        config: CheckConfig,
        disagrees: Callable[[State], tuple[bool, QueryResult, QueryResult, str | None]],
        generator: str,
        description: str,
        base: State | None,
    ) -> Finding:
        p = self.prepared

        def reproduces(candidate: World) -> bool:
            try:
                return disagrees(candidate.state)[0]
            except Exception:
                return False

        minimized = minimize_world(
            p.spec,
            world,
            base,
            reproduces,
            referenced=referenced or None,
            max_attempts=config.minimization_max_attempts,
        )
        final_state = minimized.world.state
        differs, left, right, difference = disagrees(final_state)
        final_validity = p.spec.validate(final_state)
        data = to_database_state(p.model, final_state)
        retained = _retained_tables(p.model, referenced, data)
        data = DatabaseState(tuple(t for t in data.tables if t.name in retained))
        if self.engine == "sqlite":
            reproducer = sqlite_reproducer(p.model.db, data)
            fixture = "counterexample.sql"
        else:
            assert p.pg is not None
            reproducer = postgres_reproducer(
                p.pg, data, case.reference_sql, case.candidate_sql, engine=self.engine
            )
            fixture = "counterexample.sql"
        path = [
            MutationRecord(
                family=m.family,
                target=m.target,
                description=m.description,
                hints=m.hints,
                atoms=[list(a) for a in m.atoms],
            )
            for m in world.path
        ]
        state_json = {
            t.name: [
                dict(zip(t.columns, row, strict=True))
                for row in _json_rows(p.model, final_state, t.name)
            ]
            for t in data.tables
        }
        before = minimized.atoms_before
        return Finding(
            finding_id=f"{case.case_id or 'case'}:1",
            world_id=generator or "baseline",
            validity=_validity_record(final_validity),
            oracles=[_oracle_record(NOT_MET)],
            world_diff=diff_states(base, final_state) if base is not None else {},
            mutation_path=path,
            divergence={
                "reference_result": left.model_dump(mode="json"),
                "candidate_result": right.model_dump(mode="json"),
                "difference": difference or outputs[2] or "query results differ",
                "candidate_state": state_json,
                "reproducer_sql": reproducer,
                "original_injected_change": description,
                "generator": generator,
                "reproduces": differs,
            },
            fidelity=self._fidelity(),
            replay=ReplayRecord(artifact=fixture),
            minimization={
                "complete": minimized.complete,
                "attempts": minimized.attempts,
                "rows_before": before,
                "rows_after": minimized.atoms_after,
                "changed_atoms": minimized.changed_atoms,
            },
            headline=(
                "Original-data mismatch: queries return different results"
                if generator == "original_state"
                else f"Queries diverge after a {path[-1].family if path else 'baseline'} mutation"
            ),
        )

    def _unsupported(self, case: SqlCase, message: str, started: float) -> CaseReport:
        return self._report(
            case,
            ComparisonPolicy(),
            started,
            CheckConfig(),
            status=DivergenceStatus.UNSUPPORTED,
            validity=ValidityRecord(status="NOT_ASSESSED"),
            headline=f"Unsupported SQL: {safe_detail(message)}",
            original={"outputs_match": None, "note": "Queries were not executed."},
            errors=[{"code": "UNSUPPORTED_SQL", "message": message, "phase": "input"}],
            search_result=None,
        )

    def _report(
        self,
        case: SqlCase,
        policy: ComparisonPolicy,
        started: float,
        config: CheckConfig,
        *,
        status: DivergenceStatus,
        validity: ValidityRecord,
        headline: str,
        original: dict[str, Any],
        errors: list[dict[str, str]],
        search_result: SearchResult | None,
        findings: list[Finding] | None = None,
        checked: list[str] | None = None,
    ) -> CaseReport:
        p = self.prepared
        account = search_result.accounting() if search_result is not None else None
        search_record = (
            SearchRecord(**account)
            if account is not None
            else SearchRecord(seed=config.seed, attempts=0, valid_candidates=0, executed=0)
        )
        inputs: dict[str, Any] = {
            **{k: v for k, v in p.source.items() if k != "ddl"},
            "reference_sql": case.reference_sql,
            "candidate_sql": case.candidate_sql,
            "reference_sql_sha256": sha256_text(case.reference_sql),
            "candidate_sql_sha256": sha256_text(case.candidate_sql),
            "question": case.question,
        }
        if "ddl" in p.source:
            inputs["schema_sql"] = p.source["ddl"]
        if p.domain_schema is not None:
            inputs["constraints"] = p.domain_schema
        outcome_failed = bool(findings)
        return CaseReport(
            case_id=case.case_id or "case",
            pack="sql",
            task=case.question,
            subject_kind=SubjectKind.ARTIFACT.value,
            divergence_status=status,
            validity=validity,
            execution_fidelity=self._fidelity(),
            oracles=[
                _oracle_record(
                    NOT_MET
                    if outcome_failed
                    else (None if status is not DivergenceStatus.NOT_FOUND_WITHIN_BUDGET else MET)
                )
            ],
            search=search_record,
            findings=findings or [],
            comparison_policy=policy.model_dump(mode="json"),
            inputs=inputs,
            original_state=original,
            assumptions=[
                "Generated states are validated against the schema and every supplied domain "
                "rule; domain validation does not guarantee real-world plausibility.",
                "Minimization is bounded and preserves the observed disagreement plus configured "
                "constraints; an incomplete run returns the smallest state found in its budget.",
            ],
            checked_rules=sorted(set(checked or [])),
            unused_rules=[r.name for r in p.spec.python_constraints],
            errors=errors,
            headline=headline,
            elapsed_seconds=time.monotonic() - started,
            extensions={
                "sql": {
                    "target_dialect": "sqlite" if self.engine == "sqlite" else "postgres",
                    "execution_engine": self.engine,
                    "native_verification": (
                        "NATIVE_UNVERIFIED" if self.engine == "duckdb" else "NATIVE_EXECUTION"
                    ),
                    "ordering_policy": config.ordering_policy.value,
                    "seeded": p.seeded,
                    "schema_ddl": self._ddl_statements(),
                    "translation_status": "APPLIED" if self.engine == "duckdb" else "NOT_REQUIRED",
                    "executed_reference_sql": self._executed[0],
                    "executed_candidate_sql": self._executed[1],
                }
            },
        )

    # --- suites -------------------------------------------------------------------------------

    def check_suite(
        self,
        cases: list[SuiteCase],
        config: CheckConfig | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> AuditReport:
        started = time.monotonic()
        config = config or CheckConfig()
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise SqlInputError("case IDs must be unique")
        reports: list[CaseReport] = []
        for item in cases:
            sql_case = SqlCase(
                item.reference_sql, item.candidate_sql, item.case_id, item.question, item.metadata
            )
            callback = (
                (lambda outcome, cid=item.case_id: progress(cid, outcome)) if progress else None
            )
            try:
                report = self.check(sql_case, config, callback)
            except SqlInputError as error:
                report = self._unsupported(sql_case, str(error), time.monotonic())
            except InputError:
                raise
            except Exception as error:
                report = self._report(
                    sql_case,
                    ComparisonPolicy(),
                    time.monotonic(),
                    config,
                    status=DivergenceStatus.INCONCLUSIVE,
                    validity=ValidityRecord(status="NOT_ASSESSED"),
                    headline=f"Inconclusive: {safe_detail(f'{type(error).__name__}: {error}')}",
                    original={"outputs_match": None, "note": "The case raised an error."},
                    errors=[
                        {
                            "code": "CASE_INTERNAL_ERROR",
                            "message": f"{type(error).__name__}: {error}",
                            "phase": "suite",
                        }
                    ],
                    search_result=None,
                )
            reports.append(report)
        return AuditReport(
            pack="sql",
            kind="suite",
            cases=sorted(reports, key=_priority),
            totals=totals_of(reports),
            elapsed_seconds=time.monotonic() - started,
            metadata={"engine": self.engine},
        )


def _priority(case: CaseReport) -> int:
    from isitright.core.evidence import evidence_strength

    return evidence_strength(case)


# --- shared small pieces -----------------------------------------------------------------------

MET: Literal["MET"] = "MET"
NOT_MET: Literal["NOT_MET"] = "NOT_MET"


def _oracle_record(outcome: Literal["MET", "NOT_MET"] | None) -> OracleRecord:
    return OracleRecord(
        name="reference_sql",
        kind="REFERENCE_PROGRAM",
        outcome=outcome,
        description="The reference SQL's result under the stated comparison policy.",
        limits=["The reference is an implementation too; attribution is undetermined."],
    )


def _validity_record(validity: Validity) -> ValidityRecord:
    return ValidityRecord(
        status=validity.status.value,
        tiers=[t.value for t in validity.tiers],
        problems=list(validity.problems),
        notes=list(validity.notes),
    )


def _retained_tables(model: SqlModel, referenced: list[str], data: DatabaseState) -> set[str]:
    """Tables a reader needs: those the programs read, those holding rows, and their parents."""
    keep = {t.name for t in data.tables if t.rows} | set(referenced)
    pending = list(keep)
    while pending:
        for foreign in model.db.table(pending.pop()).foreign_keys:
            if foreign.referenced_table not in keep:
                keep.add(foreign.referenced_table)
                pending.append(foreign.referenced_table)
    return keep or {t.name for t in data.tables}


def _json_rows(model: SqlModel, state: State, table: str) -> list[tuple[Any, ...]]:
    columns = model.columns(table)
    return [tuple(e.get(c) for c in columns) for e in state.entities(table)]


def _empty_table(model: SqlModel, name: str) -> Any:
    from isitright.packs.sql.state import TableState

    return TableState(name, model.columns(name), ())


def _json_schema_rule(model: SqlModel, schema: dict[str, Any]) -> PythonConstraint:
    def check(state: State) -> list[str]:
        snapshot = to_database_state(model, state).records()
        return [
            "domain constraint at "
            + ("/".join(str(p) for p in e.absolute_path) or "$")
            + f": {e.message}"
            for e in domain_errors(snapshot, schema)[:1]
        ]

    return PythonConstraint(f"json-schema:{schema.get('$id', 'anonymous')}", check)


def _validator_rule(
    model: SqlModel, validator: CandidateStateValidator, engine: str
) -> PythonConstraint:
    def check(state: State) -> list[str]:
        result = validator(StateView(model, state, engine))
        if result.status is ValidatorStatus.INDETERMINATE:
            raise RuntimeError("trusted validator could not determine state validity")
        if result.status is ValidatorStatus.INVALID:
            return [result.findings[0].message if result.findings else "validator rejected state"]
        return []

    return PythonConstraint(f"validator:{validator.name}", check)


def _readable_file(path: str | PathLike[str], label: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise InputError(f"{label} file is not readable: {path}")
    return resolved


def _check_budgets(config: CheckConfig) -> None:
    if (
        config.max_attempts < 1
        or config.timeout_seconds <= 0
        or config.max_result_rows < 1
        or config.minimization_max_attempts < 0
    ):
        raise SqlInputError("budgets must be positive")
