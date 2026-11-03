"""Hints for a data task come from the program, the schema and the question, never the gold."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")

from isitright.core.hints import Provenance
from isitright.packs.data.hints import harvest_program_hints
from isitright.packs.data.mapping import (
    TableFile,
    read_frame,
    schema_from_frames,
)

PROGRAM = """
import pandas as pd
df = pd.read_csv("sales.csv")
big = df[(df["amount"] > 100) & (df["region"] == "north")]
top = big.sort_values("amount", ascending=False).head(1)
print(df.groupby("region")["amount"].mean(), df.query("qty >= 3")["qty"].sum())
print(df[df["region"].isin(["east", "west"])].shape)
"""


@pytest.fixture
def schema_and_files(tmp_path: Path):
    (tmp_path / "sales.csv").write_text(
        "No. sold,amount,region,qty\n1,150.5,north,3\n2,90.0,south,4\n", encoding="utf-8"
    )
    files = [TableFile("sales.csv", "sales")]
    frames = {"sales": read_frame(tmp_path / "sales.csv")}
    return schema_from_frames(frames, files), files


def names(hints, kind: str) -> set[str]:
    return {h.name for h in hints.of(kind)}


def test_hints_are_harvested_from_the_program_with_their_provenance(schema_and_files) -> None:
    schema, files = schema_and_files
    hints = harvest_program_hints(PROGRAM, schema, files)
    hints.validate(schema)
    assert names(hints, "scope") == {"scope:sales"}
    assert {"column:sales.amount", "column:sales.region", "column:sales.qty"} <= names(
        hints, "column"
    )
    assert "literal:sales.region='north'" in names(hints, "literal")
    assert "literal:sales.region='east'" in names(hints, "literal")
    assert "literal:sales.amount=100" in names(hints, "literal")
    ordering = hints.get("ordering:sales.amount")
    assert ordering is not None and ordering.args["direction"] == "desc"
    threshold = hints.get("threshold:sales.amount>=100") or hints.get("threshold:sales.amount100")
    assert any(
        h.args["path"] == "sales.amount" and h.args["holds"] == "above"
        for h in hints.of("threshold")
    )
    assert any(h.args["path"] == "sales.qty" and h.args["inclusive"] for h in hints.of("threshold"))
    assert threshold is None or threshold.args["value"] == 100
    assert all(h.provenance is Provenance.HARVESTED_PROGRAM for h in hints)


def test_a_flipped_comparison_keeps_the_side_of_the_threshold(schema_and_files) -> None:
    schema, files = schema_and_files
    hints = harvest_program_hints(
        'import pandas as pd\ndf = pd.read_csv("sales.csv")\nx = df[10 > df["qty"]]', schema, files
    )
    threshold = next(h for h in hints.of("threshold") if h.args["path"] == "sales.qty")
    assert threshold.args["holds"] == "below" and threshold.args["value"] == 10


def test_columns_with_dots_use_their_alias(schema_and_files) -> None:
    schema, files = schema_and_files
    hints = harvest_program_hints(
        'import pandas as pd\ndf = pd.read_csv("sales.csv")\ndf["No. sold"]', schema, files
    )
    hints.validate(schema)
    assert any(h.kind == "column" and "sold" in h.args["field"] for h in hints)


def test_the_question_text_names_columns_with_its_own_provenance(schema_and_files) -> None:
    schema, files = schema_and_files
    hints = harvest_program_hints(
        'import pandas as pd\ndf = pd.read_csv("sales.csv")',
        schema,
        files,
        question='Mean of the "amount" per region?',
    )
    question = [h for h in hints if h.provenance is Provenance.HARVESTED_QUESTION]
    assert {h.args["field"] for h in question} == {"amount", "region"}


def test_a_program_that_does_not_parse_gives_no_hints(schema_and_files) -> None:
    schema, files = schema_and_files
    assert len(harvest_program_hints("def (:", schema, files)) == 0
