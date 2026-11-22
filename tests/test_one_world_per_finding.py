# Proposed fixture: pending owner review
# The world a finding shows is the world its evidence is about (ledger E1 to E4). The queries, rows
# and scripted agents here are invented for these tests by the assistant that also wrote the code
# under test; they are not owner-approved.
"""One world per finding: the world shown is the world confirmed, graded, diffed, replayed and
exported (ledger E1, E2, E3 and the part of E4 that N1 left open).

The first group reproduces each defect through fields that existed before this package; each test
failed on the code the package started from. The later groups state the contract: a finding names
one world (`world_fingerprint`), every part built from a world says so (`built_from`), the model
refuses a finding whose parts disagree, and each pack's artifacts hold the world the finding shows.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from isitright.core.evidence import (
    FidelityRecord,
    Finding,
    OracleRecord,
    ReplayRecord,
    ValidityRecord,
)
from isitright.core.mutations import (
    AddEntity,
    Mutation,
    RemoveEntity,
    SetField,
    SetParam,
    World,
)
from isitright.core.shown import built_from, surviving_path, world_json_fingerprint
from isitright.core.stochastic import Observation, RateWithInterval
from isitright.core.world import State

EXAMPLES = Path(__file__).parents[1] / "examples" / "agents"
SHOP_REF = f"{EXAMPLES / 'shop' / 'scenario.py'}:SCENARIO"


# -- E1: the native result belongs to the world the reproducer shows --------------------------


def test_the_world_that_differed_natively_is_the_world_the_finding_shows() -> None:
    """E1. The minimized world agreed natively and the larger one differed; the finding was marked
    verified and showed (and gave the reproducer of) the minimized one."""
    pytest.importorskip("duckdb")
    from isitright.packs.sql import ConnectionHost, check

    calls = {"n": 0}
    differed: list[str] = []

    def run(sql: str) -> tuple[list[str], list[list[Any]]]:
        if "LEFT JOIN" in sql:
            calls["n"] += 1
            if calls["n"] > 1:
                differed.append(sql)
                return ["id", "tag"], [[10, None]]
        return ["id", "tag"], []

    report = check(
        reference_sql="SELECT t.id, tag FROM items AS t LEFT JOIN UNNEST(t.tags) AS u(tag) ON TRUE",
        candidate_sql="SELECT t.id, tag FROM items AS t CROSS JOIN UNNEST(t.tags) AS u(tag)",
        dialect="presto",
        ddl="CREATE TABLE web.items (id bigint, tags array(bigint), name varchar)",
        confirm=ConnectionHost(run=run),
    )
    finding = report.findings[0]
    assert finding.fidelity.verified_on == "NATIVE_INLINE"
    assert len(differed) == 1
    rows_shown = sum(len(rows) for rows in finding.divergence["candidate_state"].values())
    rows_that_differed = differed[0].count("CAST(NULL AS VARCHAR)")  # one `name` per inlined row
    assert rows_shown == rows_that_differed, (
        f"the finding shows {rows_shown} row(s); the native engine differed on {rows_that_differed}"
    )
    attached = finding.divergence["minimized_world"]
    assert attached["fidelity"] == "EMULATED" and attached["verified"] is False
    assert sum(len(r) for r in attached["candidate_state"].values()) == 1


# -- E2: a minimized world keeps the kind of difference that was found ------------------------


def _kind(difference: str) -> str:
    if difference.startswith("row count differs"):
        return "row_count"
    if difference.startswith(("ordered row", "unordered row")):
        return "row_values"
    return difference


def test_minimization_keeps_the_kind_of_difference_it_started_from(tmp_path: Path) -> None:
    """E2. The first world differs in the number of rows; deleting the row that makes the candidate
    drop one gives a smaller world that differs in a value instead, and was kept."""
    from isitright.packs.sql import check

    database = tmp_path / "people.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            INSERT INTO people VALUES (1, 'bob'), (2, 'alice');
            """
        )
        connection.commit()
    finally:
        connection.close()
    report = check(
        database=database,
        reference_sql="SELECT id, name FROM people ORDER BY id",
        candidate_sql="SELECT id, upper(name) FROM people WHERE name <> 'bob' ORDER BY id",
    )
    found = report.original_state["note"]
    shown = report.findings[0].divergence["difference"]
    assert _kind(found) == "row_count"
    assert _kind(shown) == _kind(found), f"found: {found!r}; shown: {shown!r}"
    # the kind-preserving minimizer still reaches a one-row world (the row that makes the candidate
    # drop one); a world that merely fell back to the unminimized one would have two
    minimization = report.findings[0].minimization
    assert minimization["shown"] == "minimized" and minimization["rows_after"] == 1


# -- E3: a minimized path and the evidence of the world it came from --------------------------


@pytest.fixture(scope="module")
def minimized_shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path, str]:
    """The careless scripted agent on a composed trap world of the shop, with `--minimize`."""
    pytest.importorskip("mcp")
    from isitright.core.oracles import Role
    from isitright.packs.mcp.audit import run_scenario
    from isitright.packs.mcp.generate import generate_worlds
    from isitright.packs.mcp.model import load_scenario

    scenario = load_scenario(SHOP_REF)
    found, _ = generate_worlds(scenario, attempts=2000, depth=2)
    composed = next(
        w for w in found if w.role is Role.TRAP and w.observable and len(w.families) == 2
    )
    out = tmp_path_factory.mktemp("minimized-shop") / "out"
    os.environ["SHOP_AGENT_MODE"] = "careless"
    try:
        report = run_scenario(
            scenario_ref=SHOP_REF,
            agent_command=f'"{sys.executable}" "{EXAMPLES / "shop" / "scripted_agent.py"}"',
            output_dir=out,
            worlds="generated",
            k=2,
            attempts=2000,
            only=[composed.id],
            trust_code=True,
            timeout_seconds=60,
            minimize=True,
            minimize_max_runs=120,
            sequential=False,
        )
    finally:
        del os.environ["SHOP_AGENT_MODE"]
    return report, out, composed.id


def test_the_exported_world_is_the_world_of_the_reported_path(
    minimized_shop: tuple[Any, Path, str],
) -> None:
    """E3. With `--minimize` the finding names the minimal path while its diff, validity, counts,
    run directory and export are those of the original, longer path."""
    from isitright.packs.mcp.audit import export_eval_cases

    report, out, _ = minimized_shop
    (finding,) = report.cases[0].findings
    assert finding.minimization["minimal"] and len(finding.mutation_path) == 1
    (case,) = export_eval_cases(SHOP_REF, report, out, include_observed=True)
    exported = World.from_json(case.payload["world"])
    assert len(exported.path) == len(finding.mutation_path), (
        f"the finding names {len(finding.mutation_path)} mutation(s); "
        f"the exported world has {len(exported.path)}"
    )


# -- the data pack: the identity of a minimized frozen finding --------------------------------


def test_a_frozen_data_finding_is_identified_by_the_world_it_shows(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    from isitright.packs.data.audit import AuditConfig, DataAudit
    from isitright.packs.data.task import load_task
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    task = load_task(make_task(tmp_path / "task"))
    with DataAudit(task, AuditConfig(attempts=80, trust_code=True, reuse=20)) as audit:
        case = audit.check_frozen(program(DROPNA_FORGOTTEN, "dropna_forgotten"))
        finding = case.findings[0]
        replay_world = World.from_json(audit.artifacts[finding.finding_id].world)
    assert finding.minimization["rows_after"] < finding.minimization["rows_before"]
    assert finding.world_id == replay_world.fingerprint()
    assert finding.world_fingerprint == replay_world.fingerprint()
    assert set(finding.built_from.values()) == {finding.world_fingerprint}


# -- E4: a research finding is shown on a world it reproduces on ------------------------------


def _ghost_citation(run: Any) -> Any:
    from isitright.packs.research.runs import Citation, Claim

    ghost = Claim(text="x", citations=[Citation(doc_id="no-such-document", quote="x")])
    answer = run.report.answer or "x"
    report = run.report.model_copy(update={"claims": [ghost], "answer": answer})
    return run.model_copy(update={"report": report})


def test_a_research_finding_never_shows_a_world_that_did_not_reproduce() -> None:
    """E4. A confirmation on the shown world found no failure, and the finding was built anyway,
    labeled `reproduces_on_shown_world: False`, with the grade of the world the search ran."""
    from isitright.core.stochastic import SubjectRunner
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import Subject

    from .research_fixtures import audit

    a = audit(depth=2, runs=4, minimize=True, minimized_findings=1, max_findings=1, seed=11)
    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()
    phase = {"tag": ""}
    original_run = SubjectRunner.run

    def run_with_tag(self: Any, target: Any, tag: str = "", **kwargs: Any) -> Any:
        phase["tag"] = tag
        return original_run(self, target, tag, **kwargs)

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        if world.fingerprint() == base or phase["tag"] == "confirm":
            return run  # the baseline, and the confirmation runs, are fine
        return _ghost_citation(run)

    SubjectRunner.run = run_with_tag  # type: ignore[method-assign]
    try:
        case = a.check(Subject(careful.label, True, execute))
    finally:
        SubjectRunner.run = original_run  # type: ignore[method-assign]
    assert case.findings, case.headline
    for finding in case.findings:
        assert finding.divergence["shown_world_is_minimized"] is False or (
            finding.divergence["reproduces_on_shown_world"] is True
        ), "a finding was built on a minimized world where no run failed"


# -- SQL: a minimized world that stops reproducing is not shown ------------------------------


def _forget_second_sightings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine answers a world it has seen before with the reference's result for both queries,
    as a nondeterministic query might: a world that differed once does not differ when rerun."""
    from isitright.packs.sql import hosts

    real = hosts.SqliteHost.run_pair
    seen: dict[Any, int] = {}

    def run_pair(
        self: Any, state: Any, reference_sql: str, candidate_sql: str, **kwargs: Any
    ) -> Any:
        left, right = real(self, state, reference_sql, candidate_sql, **kwargs)
        key = tuple((table.name, table.rows) for table in state.tables)
        seen[key] = seen.get(key, 0) + 1
        return (left, left) if seen[key] >= 2 else (left, right)

    monkeypatch.setattr(hosts.SqliteHost, "run_pair", run_pair)


def _people(tmp_path: Path) -> Path:
    database = tmp_path / "people.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            INSERT INTO people VALUES (1, 'bob'), (2, 'alice');
            """
        )
        connection.commit()
    finally:
        connection.close()
    return database


def test_a_minimized_world_that_does_not_reproduce_is_not_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isitright.packs.sql import check

    _forget_second_sightings(monkeypatch)
    report = check(
        database=_people(tmp_path),
        reference_sql="SELECT id, name FROM people ORDER BY id",
        candidate_sql="SELECT id, upper(name) FROM people WHERE name <> 'bob' ORDER BY id",
    )
    (finding,) = report.findings
    assert finding.minimization["shown"] == "unminimized"
    assert "did not reproduce" in finding.minimization["reason"]
    assert finding.minimization["rows_after"] == finding.minimization["rows_before"] == 2
    assert sum(len(rows) for rows in finding.divergence["candidate_state"].values()) == 2
    assert finding.divergence["reproduces"] is True


def test_a_disagreement_that_does_not_reproduce_when_its_world_is_rerun_is_no_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isitright.core.evidence import DivergenceStatus
    from isitright.packs.sql import check

    database = tmp_path / "ids.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            "CREATE TABLE t(id INTEGER PRIMARY KEY, v INTEGER); INSERT INTO t VALUES (1, 5);"
        )
        connection.commit()
    finally:
        connection.close()
    _forget_second_sightings(monkeypatch)
    report = check(
        database=database,
        reference_sql="SELECT v FROM t",
        candidate_sql="SELECT DISTINCT v FROM t",
    )
    assert report.findings == []
    assert report.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert [e["code"] for e in report.errors] == ["NOT_REPRODUCED"]
    assert (
        "did not reproduce when the world it was found on was rerun" in report.errors[0]["message"]
    )


def test_a_sql_finding_names_only_the_mutations_the_minimized_world_still_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search found a world made by one mutation; the test adds a second, irrelevant one (a
    note nobody reads), as a composed world would carry. Minimization puts the note back, so the
    finding names the first mutation only, in its path and in its headline."""
    from isitright.packs.sql import audit as sql_audit
    from isitright.packs.sql import check

    database = tmp_path / "notes.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            "CREATE TABLE t(id INTEGER PRIMARY KEY, v INTEGER, note TEXT);"
            "INSERT INTO t VALUES (1, 5, 'a');"
        )
        connection.commit()
    finally:
        connection.close()
    real_search = sql_audit.search

    def search_with_noise(*args: Any, **kwargs: Any) -> Any:
        result = real_search(*args, **kwargs)
        noise = Mutation(
            family="boundary",
            description="a note changes",
            edits=[SetField(collection="t", key=1, path=["note"], value="zzz")],
        )
        found = result.findings[0]
        found.candidate.world = found.candidate.world.apply(noise)
        return result

    monkeypatch.setattr(sql_audit, "search", search_with_noise)
    report = check(
        database=database,
        reference_sql="SELECT v FROM t",
        candidate_sql="SELECT DISTINCT v FROM t",
    )
    (finding,) = report.findings
    assert [m.family for m in finding.mutation_path] == ["duplicate"]
    assert finding.headline == "Queries diverge after a duplicate mutation"
    assert report.headline.endswith("after a duplicate mutation")


# -- the data pack: a finding names the mutations its world still has -------------------------


def test_a_data_finding_names_only_the_mutations_the_minimized_world_still_has(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pandas")
    from isitright.core.hints import Hints
    from isitright.core.search import Evaluation, Verdict
    from isitright.packs.data.audit import AuditConfig, DataAudit
    from isitright.packs.data.task import load_task
    from tests.data_factories import DROPNA_FORGOTTEN, make_task, program

    task = load_task(make_task(tmp_path / "task"))
    cause = Mutation(
        family="missing",
        description="a north amount is missing",
        edits=[SetField(collection="orders", key=1, path=["amount"], value=None)],
    )
    noise = Mutation(
        family="boundary",
        description="a south note changes",
        edits=[SetField(collection="orders", key=3, path=["note"], value="zzz")],
    )
    with DataAudit(task, AuditConfig(attempts=10, trust_code=True, reuse=20)) as audit:
        world = World(audit.prepared.base).apply(cause).apply(noise)
        validity = audit.prepared.spec.validate_world(world.state, world.path)
        finding = audit._finding(
            program(DROPNA_FORGOTTEN, "dropna_forgotten"),
            "orders:dropna",
            1,
            world,
            validity,
            Evaluation(Verdict.DISAGREE),
            Hints(task.hints),
            [],
        )
    assert [m.family for m in finding.mutation_path] == ["missing"]
    assert finding.headline.endswith("after a missing mutation")
    assert finding.world_fingerprint == finding.world_id
    assert finding.minimization["rows_after"] < finding.minimization["rows_before"]


# -- the model: a finding names one world ----------------------------------------------------

SHOWN = "a" * 16
OTHER = "b" * 16


def _finding(**updates: Any) -> Finding:
    fields: dict[str, Any] = {
        "finding_id": "c:1",
        "world_id": "w",
        "validity": ValidityRecord(status="VALID", tiers=["STRUCTURAL"]),
        "oracles": [OracleRecord(name="o", kind="REFERENCE_PROGRAM")],
        "fidelity": FidelityRecord(found_on="NATIVE_ISOLATED"),
        "headline": "Evidence recorded for review",
    }
    fields.update(updates)
    return Finding(**fields)


def test_parts_built_from_the_world_a_finding_shows_are_accepted() -> None:
    finding = _finding(
        world_fingerprint=SHOWN, built_from=built_from(SHOWN, "validity", "world_diff")
    )
    assert finding.world_fingerprint == SHOWN


def test_a_part_built_from_another_world_is_refused() -> None:
    with pytest.raises(ValidationError, match="world_diff built from another world than the one"):
        _finding(world_fingerprint=SHOWN, built_from={"validity": SHOWN, "world_diff": OTHER})


def test_the_parts_a_finding_has_must_each_be_tied_to_its_world() -> None:
    base = built_from(SHOWN, "validity", "world_diff")
    with pytest.raises(ValidationError, match="validity, world_diff not tied"):
        _finding(world_fingerprint=SHOWN)
    with pytest.raises(ValidationError, match="replay not tied"):
        _finding(
            world_fingerprint=SHOWN, built_from=base, replay=ReplayRecord(artifact="1.replay.json")
        )
    with pytest.raises(ValidationError, match="export not tied"):
        _finding(world_fingerprint=SHOWN, built_from=base, export="1.eval-case.json")
    rate = RateWithInterval(
        failures=1, judged=2, errors=0, unjudged=0, rate=0.5, interval_low=0.1, interval_high=0.9
    )
    with pytest.raises(ValidationError, match="counts not tied"):
        _finding(
            world_fingerprint=SHOWN,
            built_from=base,
            observation=Observation(world=rate),
            evidence_grade="OBSERVED_FAILURE",
        )


def test_built_from_needs_the_fingerprint_it_is_compared_with() -> None:
    with pytest.raises(ValidationError, match="needs the `world_fingerprint`"):
        _finding(built_from={"validity": SHOWN})
    with pytest.raises(ValidationError, match="names no part of a finding"):
        _finding(world_fingerprint=SHOWN, built_from={"validity": SHOWN, "colour": SHOWN})


@pytest.mark.parametrize("key", ["reproduces", "reproduces_on_shown_world"])
def test_a_finding_that_does_not_reproduce_on_its_world_is_refused(key: str) -> None:
    parts = built_from(SHOWN, "validity", "world_diff", "divergence")
    with pytest.raises(ValidationError, match="does not reproduce on the world it shows"):
        _finding(world_fingerprint=SHOWN, built_from=parts, divergence={key: False})
    _finding(world_fingerprint=SHOWN, built_from=parts, divergence={key: True})
    # a report written before 0.9 names no world and loads as it always did
    assert _finding(divergence={key: False}).world_fingerprint is None


# -- the helpers ------------------------------------------------------------------------------


def _state(rows: list[dict[str, Any]], **params: Any) -> State:
    return State({"t": tuple(rows)}, {"t": "id"}, params)


def _mutation(family: str, *edits: Any, target: str = "state") -> Mutation:
    return Mutation(family=family, target=target, description=family, edits=list(edits))  # type: ignore[arg-type]


def test_a_mutation_survives_while_one_of_its_edits_is_still_in_effect() -> None:
    base = _state([{"id": 1, "v": "a"}], limit=5)
    added = _mutation("duplicate", AddEntity(collection="t", entity={"id": 2, "v": "a"}))
    edited = _mutation("boundary", SetField(collection="t", key=1, path=["v"], value="z"))
    removed = _mutation("missing", RemoveEntity(collection="t", key=1))
    param = _mutation("limit", SetParam(name="limit", value=9))
    response = _mutation("noise", target="response")
    traceless = _mutation("traceless")
    path = [added, edited, removed, param, response, traceless]

    everything = _state([{"id": 1, "v": "z"}, {"id": 2, "v": "a"}], limit=9)
    assert surviving_path(path, everything, base) == (added, edited, param, response, traceless)
    # the added row was minimized away, the edited field and the parameter put back, and the row
    # a mutation removed is present again: only what is not traced survives
    shrunk = _state([{"id": 1, "v": "a"}], limit=5)
    assert surviving_path(path, shrunk, base) == (response, traceless)
    gone = _state([], limit=5)
    assert surviving_path(path, gone, base) == (removed, response, traceless)
    # with no base nothing can be compared: every mutation is kept
    assert surviving_path(path, shrunk, None) == tuple(path)


def test_the_fingerprint_of_a_stored_world_is_the_fingerprint_of_the_world() -> None:
    world = World(_state([{"id": 1, "v": "a"}]), path=(_mutation("boundary"),))
    assert world_json_fingerprint(world.to_json()) == world.fingerprint()


def test_the_difference_kinds_are_error_row_count_and_row_values() -> None:
    from isitright.packs.sql.comparison import difference_kind
    from isitright.packs.sql.models import (
        CanonicalValue,
        CanonicalValueKind,
        QueryResult,
        ResultColumn,
    )
    from isitright.packs.sql.results import error_result

    def result(*values: int) -> QueryResult:
        return QueryResult(
            columns=[ResultColumn(name="a")],
            rows=[
                [CanonicalValue(kind=CanonicalValueKind.INTEGER, value=v, engine_type="INTEGER")]
                for v in values
            ],
        )

    assert difference_kind(result(1), error_result("boom")) == "error"
    assert difference_kind(result(1, 2), result(1)) == "row_count"
    assert difference_kind(result(1), result(2)) == "row_values"
    # an error on both sides is not the candidate erroring where the reference does not
    assert difference_kind(error_result("a"), error_result("b")) == "row_values"


# -- each pack: the finding's world is the world its artifacts hold ---------------------------


def test_a_sqlite_finding_reproduces_from_its_own_script_on_the_world_it_shows(
    tmp_path: Path,
) -> None:
    from isitright import check
    from isitright.packs.sql.fixture_replay import replay_fixture as replay
    from isitright.packs.sql.reports import write_case_report

    database = tmp_path / "metric.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            "CREATE TABLE metric(id INTEGER PRIMARY KEY, base INTEGER, doubled INTEGER);"
            "INSERT INTO metric VALUES (1, 1, 2), (2, 2, 4), (3, 3, 6);"
        )
        connection.commit()
    finally:
        connection.close()
    report = check(
        database=database,
        reference_sql="SELECT doubled FROM metric",
        candidate_sql="SELECT base FROM metric",
    )
    finding = report.findings[0]
    assert finding.world_fingerprint and finding.divergence["reproduces"] is True
    assert set(finding.built_from) == {"validity", "world_diff", "divergence", "replay"}
    assert set(finding.built_from.values()) == {finding.world_fingerprint}
    write_case_report(report, tmp_path / "artifacts")
    replayed = replay(
        tmp_path / "artifacts" / "case_report.json", tmp_path / "artifacts" / "counterexample.sql"
    )
    assert replayed["reproduced"]


def test_an_mcp_finding_is_built_from_the_minimal_world_run_in_its_own_right(
    minimized_shop: tuple[Any, Path, str],
) -> None:
    from isitright.packs.mcp.audit import export_eval_cases

    report, out, searched = minimized_shop
    (finding,) = report.cases[0].findings
    assert finding.minimization["adopted"] is True
    assert finding.world_id == f"{searched}.minimal"
    assert finding.divergence["found_on_world"] == searched
    run_dir = finding.divergence["example_run_dir"]
    assert run_dir.startswith(f"runs/{finding.world_id}/")
    stored = (out / run_dir / "world.json").read_text(encoding="utf-8")
    import json

    assert world_json_fingerprint(json.loads(stored)) == finding.world_fingerprint
    assert set(finding.built_from.values()) == {finding.world_fingerprint}
    # the counts are those of the runs made on the minimal world, not of the searched one
    runs = [
        r for r in report.cases[0].extensions["mcp"]["runs"] if r["world_id"] == finding.world_id
    ]
    assert finding.observation is not None
    assert finding.observation.world.judged + finding.observation.world.errors == len(runs)
    (case,) = export_eval_cases(SHOP_REF, report, out, include_observed=True)
    assert world_json_fingerprint(case.payload["world"]) == finding.world_fingerprint
    # an export refuses a recorded world that is not the finding's
    tampered = report.model_copy(deep=True)
    tampered.cases[0].findings[0] = finding.model_copy(update={"world_fingerprint": OTHER})
    with pytest.raises(ValueError, match="is not the world of finding"):
        export_eval_cases(SHOP_REF, tampered, out, include_observed=True)


def test_a_minimal_world_that_cannot_be_run_leaves_the_finding_on_the_searched_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the run budget ends before the minimal world is run, the finding stays about the world
    the search ran, with that world's own evidence, and says why the minimal path is not shown."""
    pytest.importorskip("mcp")
    from isitright.core.oracles import Role
    from isitright.packs.mcp import audit as mcp_audit
    from isitright.packs.mcp.audit import export_eval_cases, run_scenario
    from isitright.packs.mcp.generate import generate_worlds
    from isitright.packs.mcp.model import load_scenario

    scenario = load_scenario(SHOP_REF)
    found, _ = generate_worlds(scenario, attempts=2000, depth=2)
    composed = next(
        w for w in found if w.role is Role.TRAP and w.observable and len(w.families) == 2
    )
    real = mcp_audit._run_world

    def run_world(*args: Any) -> None:
        if len(args) > 7 and args[7]:  # the minimal world: the budget is gone
            return
        real(*args)

    monkeypatch.setattr(mcp_audit, "_run_world", run_world)
    monkeypatch.setenv("SHOP_AGENT_MODE", "careless")
    out = tmp_path / "out"
    report = run_scenario(
        scenario_ref=SHOP_REF,
        agent_command=f'"{sys.executable}" "{EXAMPLES / "shop" / "scripted_agent.py"}"',
        output_dir=out,
        worlds="generated",
        k=2,
        attempts=2000,
        only=[composed.id],
        trust_code=True,
        timeout_seconds=60,
        minimize=True,
        minimize_max_runs=120,
        sequential=False,
    )
    (finding,) = report.cases[0].findings
    assert finding.world_id == composed.id and len(finding.mutation_path) == 2
    assert finding.minimization["adopted"] is False
    assert (
        "budget was spent before the minimal world was run" in finding.minimization["not_adopted"]
    )
    (case,) = export_eval_cases(SHOP_REF, report, out, include_observed=True)
    assert world_json_fingerprint(case.payload["world"]) == finding.world_fingerprint
    assert len(World.from_json(case.payload["world"]).path) == 2


def _research_with_minimized_world(
    subject_fails: Any,
) -> tuple[Any, Any, World, World | None]:
    """A research audit whose minimization returns a chosen world: the searched world with one
    document less. ``subject_fails(is_minimal, call_on_it)`` decides each run on a mutated world
    (``call_on_it`` counts the runs made on that world, from 1)."""
    from isitright.core.mutations import apply_edits
    from isitright.packs.research.agents import STAND_INS
    from isitright.packs.research.audit import ResearchAudit, Subject
    from isitright.packs.research.documents import COLLECTION

    from .research_fixtures import audit

    a = audit(depth=1, runs=4, minimize=True, minimized_findings=1, max_findings=1, seed=11)
    careful = a.stand_in(STAND_INS["careful"](a.task))
    base = a.base.fingerprint()
    calls: dict[str, int] = {}
    chosen: dict[str, World] = {}

    def smaller(self: Any, world: World, *args: Any, **kwargs: Any) -> tuple[World, dict[str, Any]]:
        chosen["searched"] = world
        for entity in world.state.entities(COLLECTION):
            key = entity[world.state.keys[COLLECTION]]
            state = apply_edits(world.state, [RemoveEntity(collection=COLLECTION, key=key)])
            if self.spec.validate_world(state, world.path).status.value == "VALID":
                chosen["minimal"] = World(state, world.response_edits, world.timers, world.path)
                return chosen["minimal"], {"minimized": True, "mode": "a world chosen by the test"}
        raise AssertionError("no document can be removed")

    def execute(world: Any, seed: int) -> Any:
        run = careful.execute(world, seed)
        fingerprint = world.fingerprint()
        if fingerprint == base:
            return run
        calls[fingerprint] = calls.get(fingerprint, 0) + 1
        minimal = chosen.get("minimal")
        is_minimal = minimal is not None and fingerprint == minimal.fingerprint()
        return _ghost_citation(run) if subject_fails(is_minimal, calls[fingerprint]) else run

    original = ResearchAudit._minimize
    ResearchAudit._minimize = smaller  # type: ignore[method-assign,assignment]
    try:
        case = a.check(Subject(careful.label, True, execute))
    finally:
        ResearchAudit._minimize = original  # type: ignore[method-assign]
    return a, case, chosen["searched"], chosen.get("minimal")


def test_a_research_finding_shows_the_minimized_world_when_it_has_evidence_of_its_own() -> None:
    a, case, searched, minimal = _research_with_minimized_world(lambda is_minimal, call: True)
    (finding,) = case.findings
    assert minimal is not None
    assert finding.world_id == finding.world_fingerprint == minimal.fingerprint()
    assert finding.world_id != searched.fingerprint()
    assert finding.divergence["shown_world_is_minimized"] is True
    assert finding.divergence["found_on_world"] == searched.fingerprint()
    # the grade and the counts are those of the minimal world's own runs
    assert finding.evidence_grade is not None and finding.evidence_grade.value == "RATE_INCREASE"
    assert finding.stability is not None and finding.stability.sequential is not None
    assert finding.stability.sequential.pairs >= 1
    stored = a.artifacts[finding.finding_id].world
    assert world_json_fingerprint(stored) == finding.world_fingerprint
    assert set(finding.built_from.values()) == {finding.world_fingerprint}


def test_a_research_finding_stays_on_the_searched_world_when_the_minimized_one_does_not_fail() -> (
    None
):
    a, case, searched, minimal = _research_with_minimized_world(
        lambda is_minimal, call: not is_minimal
    )
    (finding,) = case.findings
    assert minimal is not None
    assert finding.world_id == finding.world_fingerprint == searched.fingerprint()
    assert finding.divergence["shown_world_is_minimized"] is False
    assert finding.divergence["reproduces_on_shown_world"] is True
    assert finding.minimization["adopted"] is False
    assert finding.minimization["not_adopted"]["world"] == minimal.fingerprint()
    assert finding.minimization["not_adopted"]["reason"] == "no run of the minimized world failed"
    # the evidence is the searched world's own: its paired test decided the rate increase
    assert finding.evidence_grade is not None and finding.evidence_grade.value == "RATE_INCREASE"
    stored = a.artifacts[finding.finding_id].world
    assert world_json_fingerprint(stored) == searched.fingerprint()


def test_a_rate_increase_is_never_moved_to_a_world_that_no_paired_test_decided_on() -> None:
    """The searched world's paired test decided a rate increase; the minimized world fails once
    and no paired test decides it. The rate increase stays with the world it was decided on."""
    _, case, searched, minimal = _research_with_minimized_world(
        lambda is_minimal, call: (not is_minimal) or call == 1
    )
    (finding,) = case.findings
    assert minimal is not None
    assert finding.world_id == searched.fingerprint()
    assert finding.evidence_grade is not None and finding.evidence_grade.value == "RATE_INCREASE"
    assert finding.minimization["not_adopted"]["failures"] == 1
    assert "no paired test decided a rate increase" in finding.minimization["not_adopted"]["reason"]


def test_a_deterministic_research_finding_is_built_from_the_world_its_artifact_holds() -> None:
    from .research_fixtures import run_stand_in

    a, case = run_stand_in("credulous", depth=1)
    assert case.findings
    for finding in case.findings:
        stored = a.artifacts[finding.finding_id].world
        assert finding.world_id == finding.world_fingerprint == world_json_fingerprint(stored)
        assert finding.divergence["reproduces_on_shown_world"] is True
        parts = {"validity", "world_diff", "divergence", "replay", "export"}
        assert set(finding.built_from) == parts  # no run counts: a deterministic subject
        assert set(finding.built_from.values()) == {finding.world_fingerprint}


def test_a_frozen_research_finding_is_built_from_the_world_its_artifact_holds() -> None:
    from isitright.packs.research.agents import STAND_INS

    from .research_fixtures import audit

    a = audit(depth=1)
    subject = a.stand_in(STAND_INS["careful"](a.task))
    case = a.check_frozen(subject.execute(a.base, 0))
    assert case.findings
    for finding in case.findings:
        stored = a.artifacts[finding.finding_id].world
        assert finding.world_id == finding.world_fingerprint == world_json_fingerprint(stored)
        assert finding.divergence["reproduces_on_shown_world"] is True
        assert set(finding.built_from) == {
            "validity",
            "world_diff",
            "divergence",
            "replay",
            "export",
        }
        assert set(finding.built_from.values()) == {finding.world_fingerprint}


def test_when_no_mutation_survives_the_whole_path_is_kept() -> None:
    """Minimization may remove the rows a mutation edited, so the world differs from the base by
    absence only. The change cannot be attributed to one mutation; an empty path would hide it."""
    base = _state([{"id": 1, "v": "a"}])
    edited = _mutation("retract", SetField(collection="t", key=1, path=["v"], value="z"))
    other = _mutation("boundary", SetField(collection="t", key=1, path=["w"], value="q"))
    assert surviving_path([edited, other], _state([]), base) == (edited, other)
