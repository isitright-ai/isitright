"""A data-analysis task: the question, the data files, the gold program and what is declared.

A task is a directory::

    task.yaml          id, question, files, answer policy, output files
    gold.py            the reference program (it follows the world)
    constraints.yaml   optional: domain rules (core constraint language)
    hints.yaml         optional: declared hints
    data/              optional: the data files (or ``data_dir`` in task.yaml)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from isitright.core.constraints import Constraint, constraints_from_json
from isitright.core.hints import Hint, hints_from_json
from isitright.packs.data.comparison import AnswerPolicy, FramePolicy
from isitright.packs.data.mapping import TableFile, table_name


class TaskError(ValueError):
    """A task directory is incomplete or inconsistent."""


@dataclass
class DataTask:
    id: str
    question: str
    files: list[TableFile]
    data_dir: Path
    gold: str
    policy: AnswerPolicy
    constraints: list[Constraint] = field(default_factory=list)
    hints: list[Hint] = field(default_factory=list)
    outputs: tuple[str, ...] = ()
    max_rows: int | None = None


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_task(directory: Path) -> DataTask:
    spec_path = directory / "task.yaml"
    if not spec_path.is_file():
        raise TaskError(f"{directory}: no task.yaml")
    spec = _yaml(spec_path) or {}
    gold_path = directory / "gold.py"
    if not gold_path.is_file():
        raise TaskError(f"{directory}: no gold.py")
    data_dir = Path(spec.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = directory / data_dir
    files = [
        TableFile(f["file"], f.get("table") or table_name(f["file"]), f.get("key"))
        for f in spec.get("files", [])
    ]
    if not files:
        raise TaskError(f"{spec_path}: no files")
    for item in files:
        if not (data_dir / item.file).is_file():
            raise TaskError(f"{spec_path}: data file {item.file!r} not found in {data_dir}")
    question = str(spec.get("question", ""))
    answer = spec.get("answer", {}) or {}
    base = AnswerPolicy.for_question(question)
    frame = FramePolicy(**answer["frame"]) if "frame" in answer else None
    policy = AnswerPolicy(
        abs_tol=float(answer.get("abs_tol", base.abs_tol)),
        rel_tol=float(answer.get("rel_tol", base.rel_tol)),
        basis=str(answer.get("basis", base.basis)),
        text=str(answer.get("text", base.text)),
        frame=frame,
    )
    constraints_path = directory / "constraints.yaml"
    hints_path = directory / "hints.yaml"
    return DataTask(
        id=str(spec["id"]),
        question=question,
        files=files,
        data_dir=data_dir,
        gold=gold_path.read_text(encoding="utf-8"),
        policy=policy,
        constraints=constraints_from_json(_yaml(constraints_path) or [])
        if constraints_path.is_file()
        else [],
        hints=hints_from_json(_yaml(hints_path) or []) if hints_path.is_file() else [],
        outputs=tuple(spec.get("outputs", [])),
        max_rows=spec.get("max_rows"),
    )
