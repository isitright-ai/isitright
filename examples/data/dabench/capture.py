# Proposed fixture: pending owner review
"""Capture recorded programs from a real agent on the selected tasks (the owner runs this).

It runs the agent on each task's original data, in a separate process that sees only the
environment variables you name, and writes one recorded program per run. It calls a model, so it
costs money: it prints the number of runs and does nothing without --confirm. The recorded programs
are audited with `isitright data check` (frozen mode); see the runbook.

    python capture.py <tasks dir> --agent isitright.packs.data.adapters:SmolagentsAgent \\
        --agent-kwargs '{"model": "gpt-4o-mini"}' --pass-env OPENAI_API_KEY \\
        --output programs.jsonl --runs 1 --confirm [--only 243 --only 19]

``--agent`` is a ``module:callable`` that builds a DataAgent. For PandasAI use
``isitright.packs.data.adapters:PandasAIAgent`` in a Python 3.11 environment with pandasai installed
(PandasAI 3 pins pandas<3 and Python<3.12). Nothing here is run by the repository's tests.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from isitright.packs.data.adapters import SubprocessAgent, recorded_program
from isitright.packs.data.comparison import DataComparator
from isitright.packs.data.host import DataHost
from isitright.packs.data.mapping import (
    TableFile,
    read_frame,
    schema_from_frames,
    state_from_frames,
)
from isitright.packs.data.programs import write_programs
from isitright.packs.data.task import load_task


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("tasks", type=Path)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--agent-kwargs", default="{}")
    parser.add_argument("--pass-env", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--confirm", action="store_true", help="make the model calls")
    args = parser.parse_args()
    directories = sorted(p for p in args.tasks.iterdir() if (p / "task.yaml").is_file())
    tasks = [load_task(d) for d in directories]
    if args.only:
        tasks = [t for t in tasks if t.id.split("-")[-1] in args.only or t.id in args.only]
    print(f"{len(tasks)} tasks x {args.runs} run(s) = {len(tasks) * args.runs} agent runs")
    if not args.confirm:
        print("Not run: pass --confirm to call the model (this costs money).")
        return 0
    agent = SubprocessAgent(
        args.agent,
        trust_code=True,
        pass_env=tuple(args.pass_env),
        kwargs=json.loads(args.agent_kwargs),
        timeout_seconds=args.timeout,
        name=args.agent.split(":")[-1],
        model=json.loads(args.agent_kwargs).get("model", ""),
    )
    recordings, summary = [], []
    for task in tasks:
        files = [TableFile(f.file, f.table, f.key) for f in task.files]
        frames = {f.table: read_frame(task.data_dir / f.file) for f in files}
        schema = schema_from_frames(frames, files)
        state = state_from_frames(frames, schema, files)
        host = DataHost(schema, trust_code=True, timeout_seconds=60.0)
        gold = host.run(task.gold, state).answer()[0]
        for number in range(1, args.runs + 1):
            with tempfile.TemporaryDirectory(prefix="isitright-capture-") as scratch:
                for f in task.files:
                    shutil.copyfile(task.data_dir / f.file, Path(scratch) / f.file)
                run = agent.solve(task.question, Path(scratch))
            if run.error or not run.code:
                summary.append((task.id, number, "ERROR", run.error or "no code"))
                continue
            replay = host.run(run.code, state)
            matches = (
                replay.status == "ok"
                and DataComparator(task.policy).compare(gold, replay.answer()[0]).matches
            )
            recordings.append(recorded_program(task.id, f"run-{number}", run, agent))
            summary.append((task.id, number, "MATCHES_GOLD" if matches else "DIFFERS", ""))
            print(summary[-1], flush=True)
        host.close()
    write_programs(args.output, recordings)
    print(f"wrote {len(recordings)} recorded programs to {args.output}")
    print("Audit them frozen:")
    print(
        f"  isitright data check {args.tasks} --programs {args.output} --output out/frozen "
        "--trust-code --attempts 500 --reuse 100"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
