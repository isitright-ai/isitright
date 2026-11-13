"""The runner's own functions, called in this process.

The runner normally runs in a child process, where these functions are tested through the host.
Here the pure parts (answer conversion, the audit guard's decisions, one run's bookkeeping) are
called directly: it is faster, and the child's coverage is not measured. The audit hook itself is
never installed in this process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")

import numpy as np
import pandas as pd

from isitright.packs.data import _runner
from isitright.packs.data._runner import Guard, _plain, run_one


def test_scalars_and_odd_floats_become_plain_json() -> None:
    assert _plain(None) is None and _plain(True) is True and _plain(3) == 3 and _plain("x") == "x"
    assert _plain(1.5) == 1.5
    assert _plain(float("nan")) == {"__float__": "nan"}
    assert _plain(float("inf")) == {"__float__": "inf"}


def test_numpy_values_lists_and_mappings_become_plain_json() -> None:
    assert _plain(np.float64(2.5)) == 2.5 and _plain(np.int64(7)) == 7
    assert _plain(np.array([1, 2, 3])) == [1, 2, 3]
    assert _plain((1, 2)) == [1, 2] and _plain({"a": np.int64(1)}) == {"a": 1}
    assert sorted(_plain({3, 1, 2})) == [1, 2, 3]


def test_a_frame_keeps_columns_dtypes_index_and_data() -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}, index=[10, 11])
    plain = _plain(frame)["__frame__"]
    assert plain["columns"] == ["a", "b"] and plain["index"] == [10, 11]
    assert plain["data"] == [[1, "x"], [2, "y"]] and plain["dtypes"][0] == "int64"
    series = _plain(pd.Series([1.5, 2.5], name="s"))["__frame__"]
    assert series["columns"] == ["s"] and series["data"] == [[1.5], [2.5]]


def test_what_cannot_be_converted_is_described_not_raised() -> None:
    other = _plain(object())
    assert "__other__" in other and other["__other__"].startswith("object")
    deep: Any = []
    for _ in range(10):
        deep = [deep]
    assert "nested too deep" in str(_plain(deep))


def request(work: Path, code: str, **extra: Any) -> dict[str, Any]:
    return {"work": str(work), "code": code, **extra}


def test_one_run_reports_stdout_the_final_answer_and_a_named_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    guard = Guard()
    reply = run_one(
        request(tmp_path, "print('hi')\nfinal_answer(41 + 1)\nresult = {'k': 1}"), guard
    )
    assert reply["status"] == "ok" and reply["stdout"] == "hi\n"
    assert reply["final_answer"] == 42 and reply["has_final_answer"] is True
    assert reply["result"] == {"k": 1} and reply["result_name"] == "result"
    assert reply["versions"]["python"] and "violations" not in reply


def test_an_exception_is_a_reported_error_and_exit_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    guard = Guard()
    failed = run_one(request(tmp_path, "raise ValueError('bad input')"), guard)
    assert failed["status"] == "error" and "ValueError: bad input" in failed["error"]
    left = run_one(request(tmp_path, "import sys\nresult = 1\nsys.exit(0)"), guard)
    assert left["status"] == "ok" and left["result"] == 1


def test_a_declared_output_table_is_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    code = "import pandas as pd\npd.DataFrame({'a': [1, 2]}).to_csv('out.csv', index=False)"
    reply = run_one(request(tmp_path, code, outputs=["out.csv", "missing.csv"]), Guard())
    assert reply["outputs"]["out.csv"]["__frame__"]["columns"] == ["a"]
    assert "missing.csv" not in reply["outputs"]
    (tmp_path / "broken.csv").write_bytes(b"\xff\xfe\x00 not a table \x00")
    unreadable = run_one(request(tmp_path, "pass", outputs=["broken.csv"]), Guard())
    assert "broken.csv" in unreadable["outputs"]


def guard_in(work: Path) -> Guard:
    guard = Guard()
    guard.work, guard.violations, guard.active = _runner._real(str(work)), [], True
    return guard


def test_the_guard_allows_work_inside_the_directory(tmp_path: Path) -> None:
    guard = guard_in(tmp_path)
    inside = str(tmp_path / "data.csv")
    guard("open", (inside, "w", os.O_WRONLY))
    guard("open", (inside, "r", 0))
    guard("open", (os.devnull, "w", os.O_WRONLY))
    guard("open", (3, "r", 0))  # a file descriptor, not a path
    assert guard.violations == []


def test_the_guard_refuses_a_write_outside_the_directory_and_records_it(tmp_path: Path) -> None:
    work, elsewhere = tmp_path / "work", tmp_path / "elsewhere.txt"
    work.mkdir()
    guard = guard_in(work)
    with pytest.raises(PermissionError, match="outside the working directory"):
        guard("open", (str(elsewhere), "w", os.O_WRONLY))
    assert len(guard.violations) == 1 and "elsewhere.txt" in guard.violations[0]


def test_the_guard_refuses_a_read_of_an_existing_file_outside_but_not_a_missing_one(
    tmp_path: Path,
) -> None:
    work, secret = tmp_path / "work", tmp_path / "secret.txt"
    work.mkdir()
    secret.write_text("x", encoding="utf-8")
    guard = guard_in(work)
    with pytest.raises(PermissionError, match="outside the data directory"):
        guard("open", (str(secret), "r", 0))
    guard("open", (str(tmp_path / "does-not-exist.txt"), "r", 0))  # libraries probe such paths
    assert len(guard.violations) == 1


def test_the_guard_refuses_changing_a_path_network_and_new_processes(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    guard = guard_in(work)
    with pytest.raises(PermissionError, match="changing"):
        guard("os.remove", (str(tmp_path / "other.txt"),))
    guard("os.remove", (str(work / "mine.txt"),))  # inside: allowed
    for event, what in (
        ("socket.connect", "network access"),
        ("subprocess.Popen", "starting a process"),
        ("os.system", "starting a process"),
    ):
        with pytest.raises(PermissionError, match=what):
            guard(event, ())


def test_an_inactive_guard_allows_everything(tmp_path: Path) -> None:
    guard = guard_in(tmp_path)
    guard.active = False
    guard("socket.connect", ())
    guard("open", (str(tmp_path.parent / "x.txt"), "w", os.O_WRONLY))
    assert guard.violations == []


def test_no_memory_limit_is_applied_unless_one_is_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ISITRIGHT_MEMORY_BYTES", raising=False)
    _runner._limit_memory()  # nothing to do, and nothing raised
    monkeypatch.setenv("ISITRIGHT_MEMORY_BYTES", "")
    _runner._limit_memory()


def test_the_host_and_the_runner_agree_on_the_memory_mark() -> None:
    """The runner is a standalone file and cannot import the host; the text is written twice."""
    from isitright.packs.data.host import MEMORY_MARK

    assert MEMORY_MARK == _runner.MEMORY_MARK


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX self-check; Windows uses a Job Object")
def test_the_runner_ends_itself_when_its_peak_memory_passes_the_limit() -> None:
    """A limit below what the interpreter already uses: the check must end the process at once,
    with the mark the host reads, instead of letting the program run to its end."""
    code = (
        "import time\n"
        "from isitright.packs.data import _runner\n"
        "_runner._watch_own_memory(1024 * 1024)\n"
        "time.sleep(10)\n"
        "print('survived')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == _runner.MEMORY_EXIT, completed.stderr
    assert _runner.MEMORY_MARK in completed.stderr and "over the 1 MB limit" in completed.stderr
    assert "survived" not in completed.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX self-check; Windows uses a Job Object")
def test_the_runner_starts_its_check_only_when_the_host_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def running() -> int:
        return sum(t.name == "isitright-memory" for t in threading.enumerate())

    before = running()
    monkeypatch.delenv("ISITRIGHT_MEMORY_BYTES", raising=False)
    _runner._limit_memory()
    assert running() == before
    monkeypatch.setenv("ISITRIGHT_MEMORY_BYTES", str(10**15))  # far above anything: it never fires
    _runner._limit_memory()
    assert running() == before + 1
    assert "ISITRIGHT_MEMORY_BYTES" not in os.environ  # a program cannot read the limit
