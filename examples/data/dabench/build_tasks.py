# Proposed fixture: pending owner review
"""Assemble task directories for the selected DABench questions.

Reads the fetched benchmark (data only, never run), `selection.json` and `gold.py`, and writes
``<out>/<id>/{task.yaml, gold.py, constraints.yaml?, hints.yaml?}`` where the task points at the
fetched tables. Declared constraints and hints live in ``tasks/<id>/`` next to this file.

    python build_tasks.py <dabench data dir> <out dir>
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from gold import GOLD  # noqa: E402


def build(data: Path, out: Path) -> list[str]:
    selection = json.loads((HERE / "selection.json").read_text(encoding="utf-8"))["ids"]
    questions = {}
    for line in (data / "da-dev-questions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        questions[row["id"]] = row
    built = []
    for level in ("easy", "medium", "hard"):
        for qid in selection[level]:
            question = questions[qid]
            file, code = GOLD[qid]
            if file != question["file_name"]:
                raise SystemExit(
                    f"{qid}: gold reads {file}, the question uses {question['file_name']}"
                )
            directory = out / str(qid)
            directory.mkdir(parents=True, exist_ok=True)
            text = (
                f"{question['question']}\n\nConstraints: {question['constraints']}\n\n"
                f"Answer format: {question['format']}"
            )
            (directory / "task.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": f"dabench-{qid}",
                        "level": level,
                        "question": text,
                        "data_dir": str((data / "da-dev-tables").resolve()),
                        "files": [{"file": file}],
                        "max_rows": 5000,
                    },
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (directory / "gold.py").write_text(code, encoding="utf-8")
            for name in ("constraints.yaml", "hints.yaml"):
                source = HERE / "tasks" / str(qid) / name
                if source.is_file():
                    shutil.copyfile(source, directory / name)
            built.append(str(qid))
    return built


if __name__ == "__main__":
    ids = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"built {len(ids)} task directories in {sys.argv[2]}")
