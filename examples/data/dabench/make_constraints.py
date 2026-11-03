# Proposed fixture: pending owner review
"""Declare domain constraints per data file, from its column names and the questions about it.

These are the rules a person reading the column documentation would write: counts are not
negative, a rate is between 0 and 1, a flag is 0 or 1, a categorical column has the values the
data shows and the question names. Every rule is checked against the original data first; a rule
the data itself breaks is dropped and printed (the rule was wrong, not the data). The result is
``tasks/<id>/constraints.yaml`` for every selected question that reads the file.

    python make_constraints.py <dabench data dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from isitright.packs.data.mapping import field_name, table_name

HERE = Path(__file__).parent
Rule = tuple[str, ...]

NONNEG = "nonneg"
RULES: dict[str, list[Rule]] = {
    "insurance.csv": [
        ("range", "age", "18", "100"),
        ("range", "bmi", "10", "80"),
        ("range", "children", "0", "10"),
        (NONNEG, "charges"),
        ("oneof", "sex", "female", "male"),
        ("oneof", "smoker", "no", "yes"),
        ("oneof", "region", "northeast", "northwest", "southeast", "southwest"),
    ],
    "baseball_data.csv": [
        ("range", "batting_average", "0", "1"),
        ("range", "on_base_percentage", "0", "1"),
        (NONNEG, "salary_in_thousands_of_dollars"),
        (NONNEG, "number_of_hits"),
    ],
    "gapminder_gdp_asia.csv": [(NONNEG, "gdpPercap_1982"), (NONNEG, "gdpPercap_2007")],
    "gapminder_cleaned.csv": [
        ("range", "year", "1952", "2007"),
        (NONNEG, "pop"),
        ("range", "lifeexp", "0", "100"),
        (NONNEG, "gdppercap"),
    ],
    "titanic.csv": [
        ("oneof", "Survived", "0", "1"),
        ("oneof", "Pclass", "1", "2", "3"),
        ("oneof", "Sex", "male", "female"),
        ("range", "Age", "0", "120"),
        (NONNEG, "Fare"),
        (NONNEG, "SibSp"),
        (NONNEG, "Parch"),
        ("unique", "PassengerId"),
    ],
    "hotel_data.csv": [
        ("range", "star_rating", "0", "5"),
        (NONNEG, "review_count"),
        ("range", "bubble_score", "0", "50"),
    ],
    "auto-mpg.csv": [
        ("range", "mpg", "0", "100"),
        ("oneof", "cylinders", "3", "4", "5", "6", "8"),
        (NONNEG, "displacement"),
        ("range", "modelyear", "70", "82"),
    ],
    "Credit.csv": [
        (NONNEG, "Balance"),
        (NONNEG, "Income"),
        ("range", "Age", "18", "100"),
        (NONNEG, "Limit"),
    ],
    "e5_aapl.csv": [(NONNEG, "Volume"), (NONNEG, "Open"), (NONNEG, "High"), (NONNEG, "Low")],
    "random_stock_data.csv": [
        (NONNEG, "Volume"),
        (NONNEG, "Open"),
        (NONNEG, "High"),
        (NONNEG, "Low"),
    ],
    "test_Y3wMUE5_7gLdaTN.csv": [
        (NONNEG, "ApplicantIncome"),
        (NONNEG, "CoapplicantIncome"),
        (NONNEG, "LoanAmount"),
        ("oneof", "Education", "Graduate", "Not Graduate"),
        ("oneof", "Self_Employed", "Yes", "No"),
        ("oneof", "Credit_History", "0", "1"),
        ("unique", "Loan_ID"),
    ],
    "2015.csv": [
        ("range", "Happiness Score", "0", "10"),
        ("unique", "Country"),
        ("range", "Happiness Rank", "1", "200"),
    ],
    "oecd_education_spending.csv": [(NONNEG, "Value"), ("range", "TIME", "1990", "2030")],
    "percent-bachelors-degrees-women-usa.csv": [
        ("range", "Engineering", "0", "100"),
        ("range", "Year", "1900", "2030"),
    ],
    "test_x.csv": [
        ("oneof", "IsAlone", "0", "1"),
        ("oneof", "Pclass", "1", "2", "3"),
        ("oneof", "Sex", "0", "1"),
    ],
    "unemployement_industry.csv": [(NONNEG, "Mar.2019"), (NONNEG, "Mar.2020")],
    "2014_q4.csv": [(NONNEG, "Trips over the past 24-hours (midnight to 11:59pm)")],
    "imp.score.ldlr.metabolome.csv": [(NONNEG, "importance.score")],
    "0020200722.csv": [("range", "PERIOD", "1", "10"), (NONNEG, "EVENTNUM")],
    "traj-Osak.csv": [(NONNEG, "poiDuration"), ("range", "trajLen", "1", "1000")],
    "cost_data_with_errors.csv": [("range", "max_storm_cat", "0", "5"), (NONNEG, "max_sust_wind")],
    "20170413_000000_group_statistics.csv": [
        (NONNEG, "num. calls answered"),
        (NONNEG, "avg. num. agents talking "),
    ],
}


def number(text: str) -> float | int:
    value = float(text)
    return int(value) if value.is_integer() else value


def build(frame: pd.DataFrame, file: str) -> tuple[list[dict[str, object]], list[str]]:
    table = table_name(file)
    out: list[dict[str, object]] = []
    dropped: list[str] = []
    for rule in RULES.get(file, []):
        kind, column, *args = rule
        if column not in frame.columns:
            dropped.append(f"{file}: no column {column!r}")
            continue
        series = frame[column]
        path = f"{table}.{field_name(column)}"
        numeric = pd.api.types.is_numeric_dtype(series)
        if kind == NONNEG:
            ok = numeric and bool((series.dropna() >= 0).all())
            item: dict[str, object] = {"kind": "range", "path": path, "min": 0}
        elif kind == "range":
            low, high = number(args[0]), number(args[1])
            ok = numeric and bool(series.dropna().between(low, high).all())
            item = {"kind": "range", "path": path, "min": low, "max": high}
        elif kind == "oneof":
            values: list[object] = [number(a) if numeric else a for a in args]
            ok = bool(series.dropna().isin(values).all())
            item = {"kind": "one_of", "path": path, "values": values}
        else:  # unique
            ok = bool(series.is_unique)
            item = {"kind": "unique", "collection": table, "fields": [field_name(column)]}
        if ok:
            out.append(item)
        else:
            dropped.append(f"{file}: rule {rule} is broken by the original data")
    return out, dropped


if __name__ == "__main__":
    data = Path(sys.argv[1])
    selection = json.loads((HERE / "selection.json").read_text(encoding="utf-8"))["ids"]
    questions = {}
    for line in (data / "da-dev-questions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        questions[row["id"]] = row
    cache: dict[str, list[dict[str, object]]] = {}
    for level in selection.values():
        for qid in level:
            file = questions[qid]["file_name"]
            if file not in cache:
                frame = pd.read_csv(data / "da-dev-tables" / file)
                cache[file], dropped = build(frame, file)
                for line in dropped:
                    print("dropped:", line)
            target = HERE / "tasks" / str(qid)
            target.mkdir(parents=True, exist_ok=True)
            (target / "constraints.yaml").write_text(
                "# Proposed fixture: pending owner review\n"
                + yaml.safe_dump(cache[file], sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
    print("rules per file:", {k: len(v) for k, v in cache.items()})
