# Proposed fixture: pending owner review
"""Capture recorded programs from a real agent on the selected tasks (the owner runs this).

It runs the agent on each task's original data, in a separate process that sees only the
environment variables you name, and writes one recorded program per run. It calls a model, so it
costs money: it prints the number of runs and does nothing without --confirm. The recorded programs
are audited with `isitright data check` (frozen mode); see the runbook.

    python capture.py <tasks dir> --agent isitright.packs.data.adapters:SmolagentsAgent \\
        --agent-kwargs '{"model": "gpt-6-luna", "usd_per_million_tokens": [0.10, 0.50]}' \\
        --pass-env OPENAI_API_KEY --max-money 5 \\
        --output programs.jsonl --runs 1 --confirm [--only 243 --only 19]

``--env-file FILE`` reads the variables named by ``--pass-env`` from a dotenv-style file (a variable
already in the environment wins); nothing else in the file is used and no value is printed.
``--max-money USD`` stops before the next run once the cost the agent reports reaches the cap; it
needs ``usd_per_million_tokens`` in ``--agent-kwargs``. The recorded programs are written after
every run, so a stop or a crash keeps what was captured.

``--agent`` is a ``module:callable`` that builds a DataAgent. For PandasAI use
``isitright.packs.data.adapters:PandasAIAgent`` in a Python 3.11 environment with pandasai installed
(PandasAI 3 pins pandas<3 and Python<3.12). The repository's tests run this script only against
scripted agents; it has not been run against a real model.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from isitright.packs.data.adapters import (
    SubprocessAgent,
    load_env_file,
    recorded_program,
    unset_names,
)
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


def redacted(text: str, names: list[str]) -> str:
    """The text with the value of every passed variable masked, so an error never shows a key."""
    for name in names:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "***")
    return text[:600]


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
    parser.add_argument(
        "--env-file", type=Path, help="dotenv-style file to read --pass-env names from"
    )
    parser.add_argument(
        "--max-money", type=float, help="stop once the reported cost reaches this (USD)"
    )
    args = parser.parse_args()
    directories = sorted(p for p in args.tasks.iterdir() if (p / "task.yaml").is_file())
    tasks = [load_task(d) for d in directories]
    if args.only:
        tasks = [t for t in tasks if t.id.split("-")[-1] in args.only or t.id in args.only]
    print(f"{len(tasks)} tasks x {args.runs} run(s) = {len(tasks) * args.runs} agent runs")
    if not args.confirm:
        print("Not run: pass --confirm to call the model (this costs money).")
        return 0
    kwargs = json.loads(args.agent_kwargs)
    if args.max_money is not None and "usd_per_million_tokens" not in kwargs:
        print(
            "--max-money needs usd_per_million_tokens in --agent-kwargs: without prices the agent "
            "reports no cost, so the cap could not be enforced.",
            file=sys.stderr,
        )
        return 2
    if args.env_file is not None:
        load_env_file(args.env_file, args.pass_env)
    missing = unset_names(args.pass_env)
    if missing:
        print("Not set (environment or --env-file): " + ", ".join(missing), file=sys.stderr)
        return 2
    agent = SubprocessAgent(
        args.agent,
        trust_code=True,
        pass_env=tuple(args.pass_env),
        kwargs=kwargs,
        timeout_seconds=args.timeout,
        name=args.agent.split(":")[-1],
        model=kwargs.get("model", ""),
    )
    recordings, summary = [], []
    spent, tokens_in, tokens_out, stopped, failures = 0.0, 0, 0, "", 0
    for task in tasks:
        if stopped:
            break
        files = [TableFile(f.file, f.table, f.key) for f in task.files]
        frames = {f.table: read_frame(task.data_dir / f.file) for f in files}
        schema = schema_from_frames(frames, files)
        state = state_from_frames(frames, schema, files)
        host = DataHost(schema, trust_code=True, timeout_seconds=60.0)
        gold = host.run(task.gold, state).answer()[0]
        for number in range(1, args.runs + 1):
            if args.max_money is not None and spent >= args.max_money:
                stopped = f"cost cap reached: {spent:.4f} of {args.max_money} USD"
                break
            with tempfile.TemporaryDirectory(prefix="isitright-capture-") as scratch:
                for f in task.files:
                    shutil.copyfile(task.data_dir / f.file, Path(scratch) / f.file)
                run = agent.solve(task.question, Path(scratch))
            spent += run.money or 0.0
            tokens_in += run.input_tokens
            tokens_out += run.output_tokens
            if args.max_money is not None and run.money is None and not run.error:
                stopped = "the agent reported no cost, so the cap cannot be enforced; stopped"
                break
            if run.error or not run.code:
                summary.append(
                    (task.id, number, "ERROR", redacted(run.error or "no code", args.pass_env))
                )
                print(summary[-1], flush=True)
                failures += 1
                if failures >= 3:
                    stopped = "3 runs in a row failed; stopped so a systematic problem cannot spend"
                    break
                continue
            failures = 0
            replay = host.run(run.code, state)
            matches = (
                replay.status == "ok"
                and DataComparator(task.policy).compare(gold, replay.answer()[0]).matches
            )
            recordings.append(recorded_program(task.id, f"run-{number}", run, agent))
            write_programs(args.output, recordings)  # kept even if a later run crashes or stops
            summary.append((task.id, number, "MATCHES_GOLD" if matches else "DIFFERS", ""))
            print(summary[-1], flush=True)
        host.close()
    write_programs(args.output, recordings)
    print(f"wrote {len(recordings)} recorded programs to {args.output}")
    print(f"cost reported by the agent: {spent:.4f} USD; tokens in {tokens_in}, out {tokens_out}")
    if stopped:
        print(f"Stopped early: {stopped}")
    print("Audit them frozen:")
    print(
        f"  isitright data check {args.tasks} --programs {args.output} --output out/frozen "
        "--trust-code --attempts 500 --reuse 100"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
