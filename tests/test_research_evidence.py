# Proposed fixture: pending owner review (stand-ins written by Claude; expected frozen classes).
"""Frozen replay of a recorded run, screening, stochastic subjects and budgets."""

from __future__ import annotations

from isitright.core.evidence import DivergenceStatus
from isitright.core.oracles import Role
from isitright.packs.research.agents import STAND_INS, Mixed
from isitright.packs.research.audit import Subject, in_process_executor
from isitright.packs.research.runs import Report

from .research_fixtures import audit, run_stand_in, task


def recorded_careful():
    a = audit()
    subject = a.stand_in(STAND_INS["careful"](a.task))
    run = subject.execute(a.base, 0)
    return a, run


def frozen(run, **config):
    a = audit(depth=1, **config)
    return a, a.check_frozen(run)


def by_family(report):
    return {w.mutation_path[0].family: w for w in report.worlds if len(w.mutation_path) == 1}


def test_frozen_findings_are_the_objective_ones_and_scoped_to_the_recorded_run() -> None:
    _, run = recorded_careful()
    _, report = frozen(run)
    assert report.subject_kind == "FROZEN_ARTIFACT"
    families = {f.mutation_path[0].family for f in report.findings}
    # the cited document is removed or retracted: the recorded report rests on a source that is gone
    assert families == {"remove", "retract"}
    for f in report.findings:
        assert f.mode == "frozen_trace"
        assert "not a statement about the agent" in f.divergence["scope"]
        assert len(f.divergence["documents_in_world"]) <= 3
        assert f.divergence["reproduces_on_shown_world"] is True
        assert f.divergence["shown_world_is_minimized"] is True
    assert report.controls.status == "NOT_APPLICABLE"  # nothing was regenerated: no control reached


def test_frozen_replay_reports_what_the_agent_would_now_be_shown() -> None:
    """Exposure is ranking input, not a verdict: a planted document that the recorded queries now
    return is STALE-class, and no finding is made from it."""
    _, run = recorded_careful()
    _, report = frozen(run)
    worlds = by_family(report)
    assert worlds["supersede"].screening.screening_class == "STALE"
    assert worlds["plant"].screening.screening_class == "STALE"
    assert "supersede" not in {f.mutation_path[0].family for f in report.findings}
    assert worlds["reorder"].screening.screening_class == "UNSCREENABLE"
    assert worlds["snippets"].screening.screening_class == "UNSCREENABLE"
    assert worlds["duplicate"].screening.screening_class == "UNSCREENABLE"  # only a run knows


def test_frozen_replay_cannot_know_what_the_agent_would_do() -> None:
    _, run = recorded_careful()
    _, report = frozen(run)
    ext = report.extensions["research"]
    assert ext["mode"] == "frozen" and "the report is not regenerated" in ext["subject_statement"]
    assert report.controls.detail.startswith("frozen replay")


def test_frozen_unobservable_plant_is_reported() -> None:
    from .test_research_audit import UnseenPlant

    _, run = recorded_careful()
    a = audit(depth=1, mutators=[UnseenPlant()])
    report = a.check_frozen(run)
    assert [w.validity.unobservable for w in report.worlds] == [True]
    assert report.findings == [] and "UNOBSERVABLE" in report.headline


def test_screening_skips_worlds_the_replay_says_cannot_matter_and_loses_no_family() -> None:
    _, plain = run_stand_in("credulous", depth=1)
    _, screened = run_stand_in("credulous", depth=1, screen=True)
    skipped = [w for w in screened.worlds if w.run_status == "NOT_RUN"]
    assert skipped and all(w.not_run_reason.startswith("screened out") for w in skipped)
    assert screened.search.rejected["screened_out"] == len(skipped)
    assert screened.search.executed < plain.search.executed
    assert {f.mutation_path[0].family for f in screened.findings if f.mutation_path} == {
        f.mutation_path[0].family for f in plain.findings if f.mutation_path
    }
    for w in screened.worlds:  # a world that was not run is never counted as agreeing
        assert w.run_status == "NOT_RUN" or w.oracle_outcome is not None


# -- stochastic subjects ------------------------------------------------------------------------


def test_a_stochastic_agent_gets_counts_and_a_sequential_test() -> None:
    a = audit(depth=1, runs=4)
    report = a.check(a.stand_in(Mixed(0.5)))
    assert report.subject_kind == "AGENT"
    assert report.extensions["research"]["subject"]["name"] == "mixed(0.5)"
    plant = [f for f in report.findings if f.mutation_path and f.mutation_path[0].family == "plant"]
    assert plant, "a half-credulous agent follows the planted summary in some runs"
    stab = plant[0].stability
    assert stab is not None and stab.world.n >= 1 and stab.world.not_met >= 1
    assert stab.baseline is not None and stab.baseline.n == 4
    # an observed failure is not a rate claim: a claim needs the sequential test to cross a boundary
    assert stab.rate_claim is None or stab.sequential is not None
    assert plant[0].minimization["mode"] == "mutation path, noise tolerant"


def test_baseline_flakiness_is_counted_for_a_stochastic_agent() -> None:
    """A baseline run that answers differently from the first one is a bad baseline run."""
    a = audit(depth=1, runs=4)
    inner = in_process_executor(Mixed(0.5), a.task, a.stats)
    calls = {"n": 0}

    def flaky(world, seed):
        run = inner(world, seed)
        if not world.path:
            calls["n"] += 1
            if calls["n"] == 3:  # the third baseline run answers differently
                run.report = Report(answer="1999", claims=run.report.claims)
        return run

    report = a.check(Subject(Mixed(0.5).label, True, flaky))
    assert report.extensions["research"]["baseline"]["runs"] == 4
    assert report.stability is not None and report.stability.baseline.n == 4
    assert report.stability.baseline.not_met == 1  # the run that answered 1999


def test_run_and_money_budgets_stop_the_search_and_are_accounted() -> None:
    a = audit(depth=1, max_runs=10)
    report = a.check(a.stand_in(STAND_INS["credulous"](a.task)))
    assert report.search.budget["stopped_by"] == "runs"
    assert report.search.budget["spent"]["runs"] == 10

    b = audit(depth=1, money=1.0)
    inner = in_process_executor(STAND_INS["credulous"](b.task), b.task, b.stats)

    def priced(world, seed):
        run = inner(world, seed)
        run.cost = {"money": 0.25}
        return run

    paid = b.check(Subject(STAND_INS["credulous"](b.task).label, False, priced))
    assert paid.search.budget["stopped_by"] == "money"
    assert paid.search.budget["spent"]["money"] == 1.0  # four runs of 0.25, then it is spent
    assert paid.divergence_status in {
        DivergenceStatus.COUNTEREXAMPLE_FOUND,
        DivergenceStatus.NOT_FOUND_WITHIN_BUDGET,
    }


def test_roles_are_computed_per_world_not_assumed() -> None:
    _, report = run_stand_in("careful", depth=1)
    roles = {w.mutation_path[0].family: w.role for w in report.worlds if len(w.mutation_path) == 1}
    assert roles["supersede"] == Role.CONTROL.value and roles["plant"] == Role.TRAP.value
    assert roles["retract"] == Role.CONTROL.value and roles["reorder"] == Role.TRAP.value
    assert task().gold == "1962"


def test_frozen_report_states_the_citation_level_of_the_recorded_report() -> None:
    _, run = recorded_careful()
    _, report = frozen(run)
    citations = report.extensions["research"]["baseline"]["citations"]
    assert citations["level_reached"] == "L1" and citations["l0_failures"] == []
