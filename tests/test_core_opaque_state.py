"""The core on a state that is not records: a tree of text files. No research-pack code is used.

The files are entities with a path key and an opaque text body, which is all the core needs:
atoms for diffs and minimization, a fingerprint, JSON, `without`, validity, search, shrinking and
replay all work on it unchanged. The text is edited only by this test's own mutator.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.hints import Hints
from isitright.core.minimize import minimize_world
from isitright.core.mutations import Mutation, SetField, World
from isitright.core.replay import ReplayArtifact, load_artifact, replay, write_artifact
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.world import State, diff_states, text_span

LONG = "The release notes describe the build. " * 8


def tree() -> State:
    files = [{"path": f"docs/{n}.txt", "body": f"{LONG}file {n}."} for n in "abcde"]
    return State({"files": tuple(files)}, {"files": "path"})


def spec() -> WorldSpec:
    schema = EntitySchema(
        collections=[
            CollectionSpec(
                name="files",
                key="path",
                fields=[FieldSpec(name="path"), FieldSpec(name="body")],
            )
        ]
    )
    return WorldSpec(id="tree", schema=schema)


class AppendTodo:
    """Appends a TODO line to one file's body: a span edit of opaque text."""

    family = "append_todo"
    target = "state"
    consumes: frozenset[str] = frozenset()

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        for entity in world.state.entities("files"):
            yield Mutation(
                family=self.family,
                description=f"append a TODO line to {entity['path']}",
                edits=[
                    SetField(
                        collection="files",
                        key=entity["path"],
                        path=["body"],
                        value=entity["body"] + " TODO: remove.",
                    )
                ],
                atoms=[("files", entity["path"])],
            )


def has_todo(world: World) -> bool:
    return any("TODO" in e["body"] for e in world.state.entities("files"))


def test_state_basics_do_not_need_a_record_shape() -> None:
    state = tree()
    assert state.atoms() == [("files", f"docs/{n}.txt") for n in "abcde"]
    assert State.from_json(state.to_json()).fingerprint() == state.fingerprint()
    smaller = state.without([("files", "docs/a.txt")])
    assert smaller.size() == 4 and smaller.fingerprint() != state.fingerprint()


def test_a_text_edit_is_diffed_as_a_span() -> None:
    before = tree()
    world = World(before).apply(next(iter(AppendTodo().propose(spec(), World(before), Hints()))))
    change = diff_states(before, world.state)["changed"][0]["fields"]["body"]
    assert change["span"] == {
        "start": len(LONG) + len("file a."),
        "removed": "",
        "inserted": " TODO: remove.",
    }
    short = diff_states(
        State({"files": ({"path": "p", "body": "one"},)}, {"files": "path"}),
        State({"files": ({"path": "p", "body": "two"},)}, {"files": "path"}),
    )["changed"][0]["fields"]["body"]
    assert "span" not in short  # a short value shows before and after, as it always did


def test_text_span_handles_an_inner_edit_and_identical_edges() -> None:
    assert text_span("abcXYZdef", "abcQdef") == {"start": 3, "removed": "XYZ", "inserted": "Q"}
    assert text_span("aaa", "aaaa") == {"start": 3, "removed": "", "inserted": "a"}


def test_search_minimize_and_replay_run_unchanged_on_text_files(tmp_path: Path) -> None:
    base = World(tree())
    seen: list[str] = []

    def evaluate(candidate, validity) -> Evaluation:
        seen.append(candidate.world.path[-1].description)
        return Evaluation(
            Verdict.DISAGREE if has_todo(candidate.world) else Verdict.AGREE, validity
        )

    result = search(
        spec(), base, Hints(), [AppendTodo()], evaluate, budget=Budget(attempts=20), depth=1
    )
    assert len(result.findings) == 1 and result.attempts == 1  # stopped at the first disagreement
    found = result.findings[0].candidate.world
    minimized = minimize_world(spec(), found, base.state, has_todo)
    # five documents shrink to the one the mutation touched, and the other four are gone
    touched = next(e["path"] for e in found.state.entities("files") if "TODO" in e["body"])
    assert [e["path"] for e in minimized.world.state.entities("files")] == [touched]
    assert minimized.atoms_before == 5 and minimized.atoms_after == 1
    artifact = ReplayArtifact(
        pack="opaque-test",
        case_id="t1",
        world=minimized.world.to_json(),
        expected={"has_todo": True},
    )
    path = tmp_path / "a.replay.json"
    write_artifact(path, artifact)

    def rerun(loaded: ReplayArtifact) -> dict[str, bool]:
        return {"has_todo": has_todo(World.from_json(loaded.world))}

    assert replay(load_artifact(path), rerun).reproduced
    broken = artifact.model_copy(update={"expected": {"has_todo": False}})
    outcome = replay(broken, rerun)
    assert not outcome.reproduced and "expected False, observed True" in outcome.details[0]
