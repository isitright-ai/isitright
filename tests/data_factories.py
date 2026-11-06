"""Small data-analysis tasks for the data-pack tests (synthetic; nothing from a benchmark)."""

from __future__ import annotations

from pathlib import Path

import yaml

from isitright.packs.data.programs import ProgramSource, RecordedProgram

ORDERS = """id,region,amount,note
1,north,10.0,a
2,north,20.0,b
3,south,30.0,c
4,south,,d
5,north,40.0,e
6,east,50.0,f
7,east,60.0,g
8,south,70.0,h
"""

GOLD = """
import pandas as pd
df = pd.read_csv("orders.csv")
north = df[df["region"] == "north"]["amount"].dropna()
result = {"north_mean": round(float(north.mean()), 2)}
"""

CORRECT = """
import pandas as pd
df = pd.read_csv("orders.csv")
m = df.loc[df["region"] == "north", "amount"].dropna().mean()
print(f"@north_mean[{m:.2f}]")
"""

# A typical mistake: missing amounts become zero instead of being skipped.
DROPNA_FORGOTTEN = CORRECT.replace('"amount"].dropna().mean()', '"amount"].fillna(0).mean()')

QUESTION = "What is the mean amount of the north region? Round to 2 decimal places."


def make_task(directory: Path, *, constraints: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data").mkdir(exist_ok=True)
    (directory / "data" / "orders.csv").write_text(ORDERS, encoding="utf-8")
    (directory / "gold.py").write_text(GOLD.strip() + "\n", encoding="utf-8")
    (directory / "task.yaml").write_text(
        yaml.safe_dump({"id": "orders", "question": QUESTION, "files": [{"file": "orders.csv"}]}),
        encoding="utf-8",
    )
    if constraints:
        (directory / "constraints.yaml").write_text(
            yaml.safe_dump(
                [
                    {"kind": "range", "path": "orders.amount", "min": 0, "max": 1000},
                    {
                        "kind": "one_of",
                        "path": "orders.region",
                        "values": ["north", "south", "east"],
                    },
                ]
            ),
            encoding="utf-8",
        )
    return directory


def program(code: str, program_id: str = "p", task_id: str = "orders") -> RecordedProgram:
    return RecordedProgram(
        task_id=task_id,
        program_id=program_id,
        code=code.strip() + "\n",
        source=ProgramSource(kind="constructed_stand_in", agent="test", note="a test stand-in"),
    )
