"""The data runner leaves a program's work directory before it replies.

The caller deletes a scratch work directory as soon as it has the reply. Windows refuses to delete
the working directory of a live process, so a runner that replied first and left afterwards raced
the caller's cleanup (``PermissionError: [WinError 32]`` from a live data audit).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import isitright.packs.data.host as host

RUNNER = Path(host.__file__).with_name("_runner.py")

# Drive the runner's own loop for one request in a separate process, and note where that process is
# at the moment it writes the reply. The program itself is replaced: only the order matters here.
DRIVER = """
import importlib.util, io, json, os, sys
spec = importlib.util.spec_from_file_location("runner_under_test", sys.argv[1])
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
work = sys.argv[2]

def run_one(request, guard):
    os.chdir(request["work"])
    if request.get("raise"):
        raise RuntimeError("boom")
    return {"status": "ok"}

class Replies(io.StringIO):
    def write(self, text):
        sys.__stderr__.write(f"IN_WORK={os.path.samefile(os.getcwd(), work)}\\n")
        return super().write(text)

runner._limit_memory = lambda: None
runner.run_one = run_one
sys.stdin = io.StringIO(
    json.dumps({"work": work}) + "\\n" + json.dumps({"work": work, "raise": True}) + "\\n"
)
sys.stdout = Replies()
runner.main()
"""


def test_the_runner_has_left_the_work_directory_when_it_replies(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    done = subprocess.run(
        [sys.executable, "-c", DRIVER, str(RUNNER), str(work)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ),
    )
    assert done.returncode == 0, done.stderr
    # one line per reply: a successful request and one whose run raised
    assert [line for line in done.stderr.splitlines() if line.startswith("IN_WORK=")] == [
        "IN_WORK=False",
        "IN_WORK=False",
    ], done.stderr
