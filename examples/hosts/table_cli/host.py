"""A user-written host built only on isitright's public core interfaces.

It loads a world's state into a CSV file, runs a command-line analysis program on it and reads the
output table back. Nothing here is specific to the data pack: the same shape fits any tool that
takes files in and writes a table out (the roadmap's SPSS example).
"""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isitright.core.compare import Comparison, NumericComparator
from isitright.core.constraints import Range
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.families import default_mutators
from isitright.core.hints import Hint, Hints
from isitright.core.hosts import Fidelity
from isitright.core.minimize import minimize_world
from isitright.core.mutations import Candidate, World
from isitright.core.search import Evaluation, Verdict, search
from isitright.core.spec import WorldSpec
from isitright.core.stochastic import Budget
from isitright.core.world import State

HERE = Path(__file__).parent
SCHEMA = EntitySchema(
    collections=[
        CollectionSpec(
            name="sales",
            key="id",
            fields=[
                FieldSpec(name="id", type="int"),
                FieldSpec(name="region", type="text"),
                FieldSpec(name="amount", type="float", nullable=True),
            ],
        )
    ]
)
SPEC = WorldSpec(
    id="sales", schema=SCHEMA, constraints=[Range(path="sales.amount", min=0, max=1000)]
)
HINTS = Hints(
    [
        Hint(kind="scope", name="scope:sales", args={"collection": "sales"}),
        Hint(
            kind="column",
            name="column:sales.amount",
            args={"collection": "sales", "field": "amount"},
        ),
    ]
)


def initial_state() -> State:
    rows = [
        {"id": 1, "region": "north", "amount": 10.0},
        {"id": 2, "region": "north", "amount": 20.0},
        {"id": 3, "region": "south", "amount": 30.0},
    ]
    return State({"sales": tuple(rows)}, {"sales": "id"})


@dataclass
class Prepared:
    directory: Path
    command: list[str]

    def run(self, extra: list[str], timeout: float = 30.0) -> list[dict[str, str]]:
        output = self.directory / "out.csv"
        subprocess.run(
            [
                *self.command,
                "--input",
                str(self.directory / "data.csv"),
                "--output",
                str(output),
                "--group",
                "region",
                "--value",
                "amount",
                *extra,
            ],
            check=True,
            timeout=timeout,
            capture_output=True,
        )
        with output.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


class CliTableHost:
    """Implements the core `Host` protocol: ``prepare(spec, world)`` yields a loaded world."""

    fidelity = Fidelity.NATIVE_ISOLATED

    def __init__(self, program: Path = HERE / "analyze.py") -> None:
        self.command = [sys.executable, str(program)]

    @contextmanager
    def prepare(self, spec: WorldSpec, world: World) -> Iterator[Prepared]:
        with tempfile.TemporaryDirectory(prefix="isitright-cli-") as scratch:
            directory = Path(scratch)
            columns = [f.name for f in spec.schema.collection("sales").fields]
            with (directory / "data.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(columns)
                for row in world.state.entities("sales"):
                    writer.writerow(["" if row[c] is None else row[c] for c in columns])
            yield Prepared(directory, self.command)


def reference(state: State) -> dict[str, float]:
    """The reference oracle: mean amount per region, blanks skipped."""
    sums: dict[str, list[float]] = {}
    for row in state.entities("sales"):
        if row["amount"] is not None:
            sums.setdefault(row["region"], []).append(row["amount"])
    return {k: sum(v) / len(v) for k, v in sums.items()}


def compare(state: State, table: list[dict[str, str]]) -> Comparison:
    expected, got = reference(state), {r["region"]: float(r["mean"]) for r in table}
    if set(expected) != set(got):
        return Comparison(False, f"groups differ: {sorted(expected)} vs {sorted(got)}")
    numbers = NumericComparator(1e-9, 1e-9, "floating-point noise")
    for key in expected:
        outcome = numbers.compare(expected[key], got[key])
        if not outcome.matches:
            return Comparison(False, f"{key}: {outcome.difference}")
    return Comparison(True)


def audit(extra: list[str], attempts: int = 200) -> dict[str, Any]:
    """Search for a world where the program (run with ``extra`` arguments) disagrees with the
    reference, then minimize it."""
    host = CliTableHost()
    base = World(initial_state())

    def disagrees(world: World) -> bool:
        with host.prepare(SPEC, world) as prepared:
            return not compare(world.state, prepared.run(extra)).matches

    def evaluate(candidate: Candidate, validity: Any) -> Evaluation:
        return Evaluation(
            Verdict.DISAGREE if disagrees(candidate.world) else Verdict.AGREE, validity
        )

    found = search(
        SPEC, base, HINTS, default_mutators(), evaluate, budget=Budget(attempts=attempts)
    )
    if not found.findings:
        return {"found": False, "attempts": found.attempts}
    minimized = minimize_world(
        SPEC, found.findings[0].candidate.world, base.state, disagrees, referenced=["sales"]
    )
    return {"found": True, "rows": minimized.atoms_after, "state": minimized.world.state.to_json()}
