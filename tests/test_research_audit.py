# Proposed fixture: pending owner review (the acceptance criteria are stated in the release prompt).
"""Offline acceptance on the constructed corpus with stand-in agents written by Claude.

None of these results come from a real research agent. Each assertion names the wrong
implementation it would catch in a comment where that is not obvious.
"""

from __future__ import annotations

import pytest

from isitright.core.evidence import DivergenceStatus
from isitright.core.hints import Hint, Provenance
from isitright.core.mutations import AddEntity, Mutation
from isitright.packs.research.agents import STAND_INS
from isitright.packs.research.audit import AuditConfig, ResearchAudit, ResearchInputError
from isitright.packs.research.documents import COLLECTION, documents_of
from isitright.packs.research.mutators import Plant, all_mutators
from isitright.packs.research.replaying import replay_file, write_outputs

from .research_fixtures import audit, corpus, run_stand_in, single, task

FACT = Hint(
    kind="fact_span",
    provenance=Provenance.DECLARED,
    args={
        "doc_id": "bridge-halvorsen-history",
        "quote": "The Halvorsen Bridge was completed in 1962.",
        "value": "1962",
        "answer_type": "number",
    },
)


def families(report) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for w in report.worlds:
        key = (
            w.mutation_path[0].family
            if len(w.mutation_path) == 1
            else ("baseline" if not w.mutation_path else "composed")
        )
        out.setdefault(key, []).append(w.oracle_outcome or "NONE")
    return out


# -- the credulous agent is flagged; each finding is minimal, valid, replayable, exportable -----


@pytest.mark.parametrize("family", ["plant", "supersede", "contradict"])
def test_credulous_is_flagged_by_plant_supersede_and_contradict(family, tmp_path) -> None:
    a, report = run_stand_in("credulous", depth=1)
    found = single(report, family)
    assert found, f"no {family} world flagged the credulous stand-in"
    finding = found[0]
    docs = finding.divergence["documents_in_world"]
    assert len(docs) <= 3, "minimized to at most three documents plus the question"
    assert finding.divergence["question"] == task().question
    assert finding.divergence["shown_world_is_minimized"] is True
    assert finding.divergence["reproduces_on_shown_world"] is True  # confirmed on the shown world
    assert "DOMAIN_VALIDATED" in finding.validity.tiers and finding.validity.status == "VALID"
    assert finding.divergence["subject"]["kind"] == "stand_in"
    assert "Claude" in finding.divergence["subject"]["written_by"]
    # replayable: rebuild the corpus from the artifact and reproduce the recorded outcome
    write_outputs(tmp_path, report, a.artifacts, a.exports)
    result = replay_file(tmp_path / f"{finding.finding_id.rsplit(':', 1)[1]}.replay.json")
    assert result.reproduced, result.details
    # exportable: the case carries the minimized corpus, the question and the expectation
    import json

    export = json.loads(
        (tmp_path / f"{finding.finding_id.rsplit(':', 1)[1]}.eval-case.json").read_text()
    )
    assert export["payload"]["question"] == task().question
    assert {d["id"] for d in export["payload"]["corpus"]} == {d["id"] for d in docs}
    assert export["expectation"]["statement"]


def test_the_contradict_tie_is_proposed_in_both_orders_and_only_one_flags() -> None:
    """A tie decided by id spelling must not decide the finding: the credulous stand-in follows
    the copy only when it sorts first."""
    _, report = run_stand_in("credulous", depth=1)
    outcomes = [
        w.oracle_outcome
        for w in report.worlds
        if w.mutation_path and w.mutation_path[0].family == "contradict"
    ]
    assert sorted(outcomes) == ["MET", "NOT_MET"]


def test_careful_is_not_flagged_by_any_world_and_its_controls_discriminate() -> None:
    _, report = run_stand_in("careful")  # depth two
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET
    assert report.findings == []
    assert report.controls is not None and report.controls.status == "DISCRIMINATING"
    outcomes = {o for outs in families(report).values() for o in outs}
    assert outcomes == {"MET", "CANNOT_JUDGE"}  # no world is NOT_MET
    undefined = [w for w in report.worlds if w.oracle_outcome == "CANNOT_JUDGE"]
    # only worlds where the original source is gone or retracted and a planted document is the
    # sole source of the fact
    assert undefined and all(
        len(w.mutation_path) == 2
        and w.mutation_path[0].family in ("plant", "contradict")
        and w.mutation_path[1].family in ("remove", "retract")
        for w in undefined
    )
    assert all(w.role == "unjudgeable" for w in undefined)
    assert report.search.depth_reached == 2 and report.search.executed > 50


def test_not_found_is_not_correctness() -> None:
    _, report = run_stand_in("careful", depth=1)
    assert "no disagreement found within the budget" in report.headline
    assert "correct" not in report.headline.lower()


def test_the_credulous_agent_is_not_discriminating_in_controls() -> None:
    _, report = run_stand_in("credulous", depth=1)
    assert report.controls is not None and report.controls.status == "NOT_DISCRIMINATING"
    roles = {w.role for w in report.worlds}
    assert {"control", "trap"} <= roles


# -- the non-retrieving agent is reported as such -------------------------------------------------


def test_the_non_retrieving_agent_is_reported_by_its_citations_not_scored_correct() -> None:
    _a, report = run_stand_in("non_retrieving", depth=1)
    base = report.extensions["research"]["baseline"]
    assert base["reports"][0]["answer"] == "1962"  # the answer matches the gold
    assert base["citations"]["level_reached"] == "NONE"
    assert base["citations"]["l0_failures"] == ["doc-0000: no such document"]
    assert "reach only level NONE" in report.headline
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    first = report.findings[0]
    assert first.mutation_path == [] and "baseline" in first.headline  # the baseline world itself
    assert first.divergence["citations"]["level_reached"] == "NONE"


def test_an_invented_citation_gives_no_fact_span() -> None:
    """A fact span harvested from a citation that does not exist would plant text in a document
    nobody can open; the text families are skipped and the report says why."""
    _, report = run_stand_in("non_retrieving", depth=1)
    assert families(report).keys() <= {"baseline", "out_of_scope", "reorder", "snippets"}
    assert any("no fact span" in n for n in report.search.notes)


# -- the refusing agent is not scored correct by refusing -----------------------------------------


def test_the_refusing_agent_fails_the_baseline_gate() -> None:
    a = audit()
    report = a.check(a.stand_in(STAND_INS["refusing"](a.task)))
    assert report.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert "baseline report abstains" in report.headline
    assert report.findings == [] and report.search.executed == 0


def test_the_refusing_agent_is_exposed_by_controls_when_audited_anyway() -> None:
    a = audit(allow_failing_baseline=True, depth=1, declared_hints=[FACT])
    report = a.check(a.stand_in(STAND_INS["refusing"](a.task)))
    assert report.controls is not None and report.controls.status == "NOT_DISCRIMINATING"
    outcomes = {
        (w.mutation_path[0].family, w.oracle_outcome) for w in report.worlds if w.role == "control"
    }
    # abstaining is the right behavior where the source is gone or retracted, by accident; it is
    # not where a newer edition states the value, and that control exposes it
    assert outcomes == {("supersede", "NOT_MET"), ("retract", "MET")}
    assert report.divergence_status is DivergenceStatus.COUNTEREXAMPLE_FOUND
    assert {f.mutation_path[0].family for f in report.findings} == {"supersede"}


def test_a_baseline_that_does_not_match_the_gold_is_not_audited() -> None:
    state = corpus()
    wrong = task().model_copy(update={"gold": "1999"})
    a = ResearchAudit(state, wrong, AuditConfig())
    report = a.check(a.stand_in(STAND_INS["careful"](wrong)))
    assert report.divergence_status is DivergenceStatus.INCONCLUSIVE
    assert "does not match the gold '1999'" in report.headline
    assert "taken from the constructed corpus" in report.headline
    assert report.extensions["research"]["gold"]["trust"].startswith(
        "taken from the constructed corpus"
    )


# -- unobservable changes -------------------------------------------------------------------------


class UnseenPlant(Plant):
    """A planted document that shares no term with any query."""

    def propose(self, spec, world, hints):
        yield Mutation(
            family="plant",
            description="plant a document no query retrieves",
            edits=[
                AddEntity(
                    collection=COLLECTION,
                    entity={
                        "id": "zz-unseen",
                        "title": "Quarry",
                        "text": "Granite is cut in the quarry. The xylophone completed was 1999.",
                        "provenance": {
                            "kind": "plant",
                            "derived_from": "bridge-halvorsen-history",
                            "span": "x",
                            "replaced": "1962",
                            "value": "1999",
                        },
                    },
                )
            ],
            atoms=[(COLLECTION, "zz-unseen")],
            hints=["fact_span"],
        )


def test_a_plant_no_query_can_retrieve_is_unobservable_not_an_agent_finding() -> None:
    a = audit(depth=1, mutators=[UnseenPlant()])
    report = a.check(a.stand_in(STAND_INS["credulous"](a.task)))
    unobserved = [w for w in report.worlds if w.validity.unobservable]
    assert len(unobserved) == 1
    assert report.findings == []
    assert report.search.rejected == {"unobservable_change": 1}
    assert "UNOBSERVABLE" in report.headline
    assert report.extensions["research"]["unobservable_changes"] == [
        "plant a document no query retrieves"
    ]


def test_an_observable_plant_is_not_reported_unobservable() -> None:
    a = audit(depth=1, mutators=[Plant()])
    report = a.check(a.stand_in(STAND_INS["credulous"](a.task)))
    assert not any(w.validity.unobservable for w in report.worlds)


# -- relational families and the rank-sensitive stand-in -----------------------------------------


def test_out_of_scope_and_duplicate_do_not_change_the_careful_answer() -> None:
    _, report = run_stand_in("careful")
    for family in ("out_of_scope", "duplicate"):
        assert set(families(report)[family]) == {"MET"}
    flips = report.extensions["research"]["flip_table"]
    assert (
        flips["out_of_scope"]["answer_changed"] == 0 and flips["duplicate"]["answer_changed"] == 0
    )


def test_the_rank_sensitive_stand_in_is_caught_by_reorder_and_the_careful_one_is_not() -> None:
    _, snippet = run_stand_in("snippet_reader", depth=1)
    _, careful = run_stand_in("careful", depth=1)
    assert any(f.mutation_path and f.mutation_path[0].family == "reorder" for f in snippet.findings)
    assert families(careful)["reorder"] == ["MET"]
    assert families(careful)["snippets"] == ["MET"]


# -- budgets, errors and inputs -------------------------------------------------------------------


def test_the_attempt_budget_is_respected_and_reported() -> None:
    _, report = run_stand_in("careful", attempts=5)
    assert report.search.attempts == 5
    assert report.search.budget["stopped_by"] == "attempts"
    assert report.divergence_status is DivergenceStatus.NOT_FOUND_WITHIN_BUDGET


def test_an_invalid_corpus_is_refused_with_the_rule() -> None:
    from isitright.core.mutations import SetField, apply_edits

    bad = apply_edits(
        corpus(),
        [
            SetField(
                collection=COLLECTION, key="tolls-norrvik-2022", path=["date"], value="2001-01-01"
            )
        ],
    )
    with pytest.raises(ResearchInputError, match="supersedes_is_newer"):
        ResearchAudit(bad, task())


def test_a_crashing_subject_is_a_subject_error_not_a_finding() -> None:
    class Crash:
        stochastic = False
        label = STAND_INS["careful"](task()).label

        def run(self, tools, t, seed):
            tools.search("x", 1)
            raise RuntimeError("boom")

    a = audit(depth=1)
    report = a.check(a.stand_in(Crash()))  # type: ignore[arg-type]
    assert report.divergence_status is DivergenceStatus.UNSUPPORTED
    assert "baseline run did not complete" in report.headline
    assert report.findings == []


def test_every_result_says_which_subject_produced_it() -> None:
    _, report = run_stand_in("credulous", depth=1)
    ext = report.extensions["research"]
    assert (
        ext["subject"]["kind"] == "stand_in"
        and "stand-in agent written by Claude" in ext["subject_statement"]
    )
    assert report.subject_kind == "AGENT" and report.attribution_status.value == "UNDETERMINED"
    assert ext["classification_label"].startswith("a proposal by the implementing assistant")
    assert report.execution_fidelity.found_on == "SIMULATED"


def test_documents_of_the_original_corpus_are_never_edited_by_the_audit() -> None:
    a, _ = run_stand_in("credulous", depth=1)
    assert documents_of(a.state) == documents_of(corpus())
    assert len(all_mutators()) == 9


def test_the_careful_stand_in_uses_the_newer_source_and_says_so() -> None:
    """The oracle also accepts a stated conflict, so the agent's own behavior is pinned here: it
    answers the newer value, cites the newer edition and flags both the conflict and the newer
    source, because it reads dates."""
    from isitright.core.mutations import World
    from isitright.packs.research.agents import ToolClient
    from isitright.packs.research.hints import hints_from_run
    from isitright.packs.research.mutators import Supersede

    a = audit()
    agent = STAND_INS["careful"](a.task)
    base = a.stand_in(agent).execute(a.base, 0)
    hints = hints_from_run(base, "number", a.task.question, documents_of(a.state))
    (mutation,) = list(Supersede().propose(a.spec, a.base, hints))
    world: World = a.base.apply(mutation)
    report = agent.run(ToolClient(a.host(world)), a.task, 0)
    assert report.answer == "1965"
    assert report.claims[0].citations[0].doc_id == "supersede-bridge-halvorsen-history"
    assert report.flags == ["conflict", "newer_source"]


def test_replay_notices_a_world_that_is_not_the_one_the_run_saw(tmp_path) -> None:
    import json

    a, report = run_stand_in("credulous", depth=1)
    write_outputs(tmp_path, report, a.artifacts, a.exports)
    path = tmp_path / "1.replay.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = data["world"]["state"]["collections"]["documents"]
    docs[0]["text"] = docs[0]["text"].replace("completed", "finished")  # a different corpus
    path.write_text(json.dumps(data), encoding="utf-8")
    result = replay_file(path)
    assert not result.reproduced
    assert any("trace_reproduced: expected True, observed False" in d for d in result.details)
