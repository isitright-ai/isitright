"""Tables as worlds: states, files and the null conventions at each boundary."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from isitright.core.world import State  # noqa: E402
from isitright.packs.data.mapping import (  # noqa: E402
    MAX_ROWS,
    ROW_KEY,
    TableFile,
    UnsupportedTable,
    column_name,
    field_name,
    read_frame,
    representability_rule,
    round_trip_problems,
    schema_from_frames,
    state_from_frames,
    table_name,
    write_state,
)


def _frames(
    csv_text: str, tmp_path: Path, name: str = "t.csv"
) -> tuple[dict[str, Any], list[TableFile]]:
    path = tmp_path / name
    path.write_text(csv_text, encoding="utf-8")
    file = TableFile(name, table_name(name))
    return {file.table: read_frame(path)}, [file]


def test_table_names_are_identifiers() -> None:
    assert table_name("2015.csv") == "t_2015"
    assert table_name("DES=+2006261.csv") == "DES_2006261"
    assert table_name("percent-bachelors.csv") == "percent_bachelors"


def test_a_table_becomes_row_entities_with_a_synthetic_key(tmp_path: Path) -> None:
    frames, files = _frames("a,b,c\n1,x,2.5\n2,,3.5\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    spec = schema.collection("t")
    assert spec.key == ROW_KEY
    assert {f.name: f.type for f in spec.fields} == {
        ROW_KEY: "int",
        "a": "int",
        "b": "text",
        "c": "float",
    }
    assert spec.field("b").nullable and not spec.field("a").nullable
    rows = state.entities("t")
    assert rows[0] == {ROW_KEY: 0, "a": 1, "b": "x", "c": 2.5}
    assert rows[1]["b"] is None  # a missing cell is None, never NaN
    assert all(not isinstance(v, float) or math.isfinite(v) for r in rows for v in r.values())


def test_the_state_round_trips_to_the_same_frame(tmp_path: Path) -> None:
    frames, files = _frames("a,b,c,d\n1,x,2.5,True\n2,y,3.0,False\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    assert round_trip_problems(state, schema, frames, tmp_path / "out") == []
    again = pd.read_csv(tmp_path / "out" / "t.csv")
    assert list(again.dtypes.astype(str)) == list(frames["t"].dtypes.astype(str))
    assert again["c"].dtype.kind == "f"  # whole floats keep a decimal point, so they stay float


def test_an_integer_column_that_gains_a_null_reads_back_as_float(tmp_path: Path) -> None:
    frames, files = _frames("a,b\n1,x\n2,y\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    mutated = state.evolve({"t": [{**state.entities("t")[0], "a": None}, state.entities("t")[1]]})
    write_state(mutated, schema, tmp_path / "out")
    frame = pd.read_csv(tmp_path / "out" / "t.csv")
    assert frame["a"].dtype.kind == "f" and frame["a"].isna().tolist() == [True, False]


def test_dates_are_text_in_the_file_and_dates_in_the_schema(tmp_path: Path) -> None:
    frames, files = _frames(
        "d,t\n2024-01-02,2024-01-02 10:00\n2024-02-03,2024-02-03 11:30:15\n", tmp_path
    )
    spec = schema_from_frames(frames, files).collection("t")
    assert spec.field("d").type == "date" and spec.field("t").type == "datetime"


def test_dots_in_column_names_are_aliased_and_restored(tmp_path: Path) -> None:
    frames, files = _frames("No. of cases,x\n3,1\n4,2\n", tmp_path)
    schema = schema_from_frames(frames, files)
    assert field_name("No. of cases") != "No. of cases" and "." not in field_name("a.b")
    assert column_name(field_name("No. of cases")) == "No. of cases"
    state = state_from_frames(frames, schema, files)
    write_state(state, schema, tmp_path / "out")
    header = (tmp_path / "out" / "t.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "No. of cases,x"
    assert round_trip_problems(state, schema, frames, tmp_path / "again") == []


def test_unsupported_tables_say_why(tmp_path: Path) -> None:
    frames, files = _frames("a,b\n1,2\n", tmp_path)
    frames["t"].columns = ["a", "a"]
    with pytest.raises(UnsupportedTable, match="duplicate"):
        schema_from_frames(frames, files)
    frames, files = _frames("a\n" + "1\n" * (MAX_ROWS + 1), tmp_path, "big.csv")
    with pytest.raises(UnsupportedTable, match="rows"):
        schema_from_frames(frames, files)
    frames, files = _frames("a\n1\n", tmp_path, "m.csv")
    frames["m"] = pd.DataFrame({"a": [1, "x"]})
    with pytest.raises(UnsupportedTable, match="mixed"):
        schema_from_frames(frames, files)
    (tmp_path / "x.xlsx").write_bytes(b"")
    with pytest.raises(UnsupportedTable, match="CSV"):
        read_frame(tmp_path / "x.xlsx")


def test_values_a_csv_cannot_carry_are_invalid(tmp_path: Path) -> None:
    frames, files = _frames("a,b\nx,1.5\ny,2.5\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    rule = representability_rule(schema)
    assert rule.tier == "STRUCTURAL" and rule.check_fn(state) == []
    rows = [dict(r) for r in state.entities("t")]
    rows[0]["a"] = "NA"
    rows[1]["b"] = float("nan")
    problems = rule.check_fn(state.evolve({"t": rows}))
    assert len(problems) == 2 and "round trip" in problems[0] and "finite" in problems[1]


def test_na_strings_in_the_file_become_none(tmp_path: Path) -> None:
    frames, files = _frames("a\nNA\nx\nnull\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    assert [r["a"] for r in state.entities("t")] == [None, "x", None]


def test_a_declared_key_column_is_the_key(tmp_path: Path) -> None:
    frames, _ = _frames("id,v\n1,2\n3,4\n", tmp_path)
    files = [TableFile("t.csv", "t", key="id")]
    schema = schema_from_frames(frames, files)
    assert schema.collection("t").key == "id"


def test_parquet_round_trips_with_nullable_integers(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    frames, files = _frames("a,b\n1,x\n2,y\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    write_state(state, schema, tmp_path / "pq", fmt="parquet")
    again = read_frame(tmp_path / "pq" / "t.parquet")
    assert again["a"].tolist() == [1, 2] and again["b"].tolist() == ["x", "y"]


def test_state_is_plain_data(tmp_path: Path) -> None:
    frames, files = _frames("a\n1\n", tmp_path)
    schema = schema_from_frames(frames, files)
    state = state_from_frames(frames, schema, files)
    assert State.from_json(state.to_json()).fingerprint() == state.fingerprint()
