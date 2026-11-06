"""Tables as worlds: a data file becomes a collection of row entities and back.

A table is a collection, a row is an entity, and ``__row`` is a synthetic key (the position in the
original file) unless the task declares a key column. Values are plain Python scalars; a missing
cell is ``None`` (an empty CSV field). The physical dtypes of a mutated world are whatever pandas
infers from the written file, because that is what a program reading the file sees. See
`docs/data.md` for the null conventions and what is unsupported.
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from isitright.core.constraints import PythonConstraint
from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
from isitright.core.world import State

ROW_KEY = "__row"
MAX_ROWS = 5000
NA_STRINGS = frozenset(
    {"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN"}
    | {"<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"}
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")


DOT = "․"  # noqa: RUF001 - ONE DOT LEADER, deliberately not a full stop
"""Entity paths are dotted, so a dot in a column name is stored as U+2024 (one dot leader) and put
back when the file is written."""


def field_name(column: str) -> str:
    return column.replace(".", DOT)


def column_name(field: str) -> str:
    return field.replace(DOT, ".")


class UnsupportedTable(ValueError):
    """The table cannot be represented faithfully; the message says why."""


@dataclass(frozen=True)
class TableFile:
    """A data file the task reads: its file name, the collection it becomes and an optional key."""

    file: str
    table: str
    key: str | None = None


def table_name(file: str) -> str:
    """A collection name for a file: the stem with non-alphanumerics replaced by ``_``."""
    stem = re.sub(r"[^0-9A-Za-z]+", "_", Path(file).stem).strip("_") or "table"
    return stem if not stem[0].isdigit() else f"t_{stem}"


def read_frame(path: Path) -> pd.DataFrame:
    """The frame a program gets from ``pd.read_csv(file)`` (or Parquet) with defaults."""
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".csv", ".txt"}:
        return pd.read_csv(path)
    raise UnsupportedTable(f"{path.name}: only CSV and Parquet files are supported")


def _scalar(value: Any) -> Any:
    """A pandas/numpy cell as a plain Python value; every kind of missing becomes None."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    item = getattr(value, "item", None)
    if item is not None and not isinstance(value, str | bytes):
        value = item()
        if isinstance(value, float) and math.isnan(value):
            return None
    return value


def _logical_type(series: pd.Series[Any]) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "float"
    values = [v for v in series.tolist() if isinstance(v, str)]
    kinds = {type(v) for v in series.dropna().tolist()}
    if kinds - {str, bool}:
        raise UnsupportedTable(f"column {series.name!r} holds mixed or unsupported values")
    if kinds == {bool}:
        return "bool"
    if values and all(_DATE.match(v) for v in values):
        return "date"
    if values and all(_DATETIME.match(v) for v in values):
        return "datetime"
    return "text"


def schema_from_frames(
    frames: Mapping[str, pd.DataFrame], files: Iterable[TableFile]
) -> EntitySchema:
    """The entity schema of the frames. Raises `UnsupportedTable` with the reason."""
    by_table = {f.table: f for f in files}
    collections = []
    for table, frame in frames.items():
        if len(frame) > MAX_ROWS:
            raise UnsupportedTable(f"{table}: {len(frame)} rows (limit {MAX_ROWS})")
        if not isinstance(frame.index, pd.RangeIndex) or isinstance(frame.columns, pd.MultiIndex):
            raise UnsupportedTable(f"{table}: a non-default index or multi-level columns")
        names = [str(c) for c in frame.columns]
        if len(set(names)) != len(names):
            raise UnsupportedTable(f"{table}: duplicate column names")
        for name in names:
            if name == ROW_KEY or DOT in name:
                raise UnsupportedTable(f"{table}: column name {name!r} is not supported")
        declared = by_table[table].key if table in by_table else None
        fields = [FieldSpec(name=ROW_KEY, type="int")]
        for name in names:
            series = frame[name]
            kind = _logical_type(series)
            fields.append(
                FieldSpec(name=field_name(name), type=kind, nullable=bool(series.isna().any()))  # type: ignore[arg-type]
            )
        collections.append(CollectionSpec(name=table, key=declared or ROW_KEY, fields=fields))
    return EntitySchema(collections=collections)


def state_from_frames(
    frames: Mapping[str, pd.DataFrame], schema: EntitySchema, files: Iterable[TableFile]
) -> State:
    names = {f.table: f.file for f in files}
    collections: dict[str, tuple[dict[str, Any], ...]] = {}
    for table, frame in frames.items():
        rows = []
        for position, record in enumerate(frame.to_dict(orient="records")):
            row: dict[str, Any] = {ROW_KEY: position}
            row.update({field_name(str(k)): _scalar(v) for k, v in record.items()})
            rows.append(row)
        collections[table] = tuple(rows)
    return State(collections, schema.keys(), {"files": names})


def _cell(value: Any, kind: str) -> str:
    if value is None:
        return ""
    if kind == "float":
        return repr(float(value))
    if kind == "bool":
        return "True" if value else "False"
    return str(value)


def write_state(state: State, schema: EntitySchema, directory: Path, fmt: str = "csv") -> None:
    """Write each table to its file in ``directory``. ``__row`` is not written."""
    directory.mkdir(parents=True, exist_ok=True)
    files: Mapping[str, str] = state.params["files"]
    for spec in schema.collections:
        columns = [f for f in spec.fields if f.name != ROW_KEY]
        rows = state.entities(spec.name)
        target = directory / files[spec.name]
        if fmt == "parquet":
            frame = pd.DataFrame(
                {column_name(f.name): [r.get(f.name) for r in rows] for f in columns}
            )
            frame.to_parquet(target.with_suffix(".parquet"), index=False)
            continue
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow([column_name(f.name) for f in columns])
            for row in rows:
                writer.writerow([_cell(row.get(f.name), f.type) for f in columns])


def round_trip_problems(
    state: State, schema: EntitySchema, frames: Mapping[str, pd.DataFrame], directory: Path
) -> list[str]:
    """Where the written state reads back differently from the frames it came from.

    A table that does not round trip cannot be audited honestly: the base world would already differ
    from the data the agent was given.
    """
    write_state(state, schema, directory)
    files: Mapping[str, str] = state.params["files"]
    problems = []
    for table, original in frames.items():
        again = read_frame(directory / files[table])
        if list(again.columns) != list(original.columns):
            problems.append(f"{table}: columns differ after writing")
        elif not again.equals(original) and not _equal_ignoring_dtype_names(again, original):
            problems.append(f"{table}: values or dtypes differ after writing and reading back")
    return problems


def _equal_ignoring_dtype_names(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    """Equal values, and the same kind of dtype column by column (``object`` vs ``str``)."""
    if left.shape != right.shape:
        return False
    for name in left.columns:
        a, b = left[name], right[name]
        if pd.api.types.is_numeric_dtype(a) != pd.api.types.is_numeric_dtype(b):
            return False
        if pd.api.types.is_numeric_dtype(a):
            if a.dtype != b.dtype or not a.equals(b):
                return False
        elif a.fillna("\0").astype(str).tolist() != b.fillna("\0").astype(str).tolist():
            return False
    return True


def representability_rule(schema: EntitySchema) -> PythonConstraint:
    """Values a CSV cannot carry: a non-finite float, and text that reads back as missing."""
    text = [
        (c.name, f.name)
        for c in schema.collections
        for f in c.fields
        if f.type in {"text", "date", "datetime"}
    ]
    floats = [(c.name, f.name) for c in schema.collections for f in c.fields if f.type == "float"]

    def check(state: State) -> list[str]:
        problems: list[str] = []
        for table, name in text:
            for row in state.entities(table):
                value = row.get(name)
                if isinstance(value, str) and value in NA_STRINGS:
                    problems.append(f"{table}.{name}={value!r} does not survive a CSV round trip")
                    break
        for table, name in floats:
            for row in state.entities(table):
                value = row.get(name)
                if isinstance(value, float) and not math.isfinite(value):
                    problems.append(f"{table}.{name}={value!r} is not finite")
                    break
        return problems

    return PythonConstraint(
        "csv_representable",
        check,
        "values must survive writing to CSV and reading back with pandas",
        tier="STRUCTURAL",
    )
