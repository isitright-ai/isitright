# Proposed fixture: pending owner review
"""Write the constructed stand-in programs as recorded programs (JSONL).

Every program is labeled ``constructed_stand_in``: written by Claude, not produced by an agent.

    python write_programs.py <out.jsonl>
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from programs import CORRECT, MISTAKES  # noqa: E402

from isitright.packs.data.programs import ProgramSource, RecordedProgram, write_programs  # noqa: E402

NOTE = "constructed stand-in written by Claude; not an external agent's output"


def stand_ins() -> list[RecordedProgram]:
    out = []
    for task, code in sorted(CORRECT.items()):
        out.append(_program(task, "correct", code))
    for task, kind, old, new in MISTAKES:
        code = CORRECT[task]
        if code.count(old) != 1:
            raise SystemExit(f"{task} {kind}: {old!r} occurs {code.count(old)} times")
        out.append(_program(task, kind, code.replace(old, new)))
    return out


def _program(task: int, kind: str, code: str) -> RecordedProgram:
    return RecordedProgram(
        task_id=f"dabench-{task}",
        program_id=kind,
        code=code,
        source=ProgramSource(kind="constructed_stand_in", agent="constructed", note=NOTE),
    )


if __name__ == "__main__":
    programs = stand_ins()
    write_programs(Path(sys.argv[1]), programs)
    print(f"wrote {len(programs)} programs")
