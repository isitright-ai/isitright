"""The data host: what it runs, what it limits, and what it records. Not a security boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pandas")

from isitright.packs.data.host import (
    MEMORY_MARK,
    DataHost,
    UntrustedCodeError,
    memory_enforcement,
)
from isitright.packs.data.mapping import (
    TableFile,
    read_frame,
    schema_from_frames,
    state_from_frames,
)
from isitright.packs.data.programs import scan_program


@pytest.fixture
def world(tmp_path: Path) -> tuple[Any, Any]:
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,x\n2,y\n3,z\n", encoding="utf-8")
    files = [TableFile("t.csv", "t")]
    frames = {"t": read_frame(path)}
    schema = schema_from_frames(frames, files)
    return schema, state_from_frames(frames, schema, files)


def make_host(world: tuple[Any, Any], **kwargs: Any) -> DataHost:
    kwargs.setdefault("trust_code", True)
    kwargs.setdefault("timeout_seconds", 20.0)
    return DataHost(world[0], **kwargs)


def test_a_program_does_not_run_without_the_opt_in(world: tuple[Any, Any]) -> None:
    host = make_host(world, trust_code=False)
    with pytest.raises(UntrustedCodeError):
        host.run("print(1)", world[1])


def test_the_answer_comes_from_final_answer_then_result_then_stdout(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        run = host.run("print('out')\nresult = 5\nfinal_answer(7)", world[1])
        assert run.status == "ok" and run.answer() == (7, "final_answer")
        run = host.run("print('out')\nresult = {'a': 1.5}", world[1])
        assert run.answer() == ({"a": 1.5}, "result")
        run = host.run("print('  @n[3]  ')", world[1])
        assert run.answer() == ("@n[3]", "stdout")
        assert host.run("x = 1", world[1]).answer() == (None, "none")
    finally:
        host.close()


def test_the_program_reads_the_world_by_file_name_and_the_versions_are_recorded(
    world: tuple[Any, Any],
) -> None:
    host = make_host(world)
    try:
        run = host.run(
            "import pandas as pd\ndf = pd.read_csv('t.csv')\nresult = {'rows': int(len(df))}",
            world[1],
        )
        assert run.answer()[0] == {"rows": 3}
        assert {"python", "pandas"} <= set(run.versions)
    finally:
        host.close()


def test_a_frame_answer_keeps_its_columns_dtypes_and_index(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        run = host.run("import pandas as pd\nresult = pd.read_csv('t.csv')", world[1])
        frame = run.answer()[0]["__frame__"]
        assert frame["columns"] == ["a", "b"] and frame["index"] == [0, 1, 2]
        assert frame["dtypes"][0].startswith("int") and frame["data"][0] == [1, "x"]
    finally:
        host.close()


def test_an_exception_is_reported_not_raised(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        run = host.run("raise ValueError('boom')", world[1])
        assert run.status == "error" and "ValueError: boom" in run.error
    finally:
        host.close()


def test_a_program_that_prints_nothing_has_no_answer(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        run = host.run("pass", world[1])
        assert run.status == "ok" and run.answer() == (None, "none")
    finally:
        host.close()


def test_a_runaway_program_times_out_and_the_next_run_gets_a_new_process(
    world: tuple[Any, Any],
) -> None:
    host = make_host(world, timeout_seconds=1.5, reuse=50)
    try:
        before = host.run("import os\nresult = os.getpid()", world[1]).answer()[0]
        run = host.run("while True:\n    pass", world[1])
        assert run.status == "timeout"
        after = host.run("import os\nresult = os.getpid()", world[1])
        assert after.status == "ok" and after.answer()[0] != before
    finally:
        host.close()


ONE_CALL = "x = bytearray(1500 * 1024 * 1024)\nresult = len(x)"
"""Allocates and touches 1.5 GB in one C call, which holds the interpreter lock throughout."""
CHUNKS = (
    "chunks = []\nfor _ in range(96):\n    chunks.append(bytearray(16 * 1024 * 1024))\nresult = 1"
)
"""Allocates 1.5 GB in 16 MB steps: the fast allocator, with the lock released between steps."""


@pytest.mark.parametrize("program", [ONE_CALL, CHUNKS], ids=["one-call", "chunks"])
def test_a_memory_limit_stops_a_program_that_allocates_too_much(
    world: tuple[Any, Any], program: str
) -> None:
    """On every platform where CI runs: a Job Object on Windows, the watchdog on Linux and macOS
    (psutil is part of the data extra)."""
    host = make_host(world, memory_mb=300)
    try:
        assert host.describe()["memory_enforcement"] == (
            "job_object" if sys.platform == "win32" else "rss_watchdog"
        )
        run = host.run(program, world[1])
        assert run.status == "memory", (run.status, run.error, run.stderr)
        assert run.answer()[0] is None
        if sys.platform != "win32":  # stopped from outside, or by the runner's own check
            assert "watchdog" in run.error or MEMORY_MARK in run.stderr, (run.error, run.stderr)
    finally:
        host.close()


def test_a_program_under_the_memory_limit_is_left_alone(world: tuple[Any, Any]) -> None:
    host = make_host(world, memory_mb=400)
    try:
        run = host.run("x = bytearray(100 * 1024 * 1024)\nresult = len(x)", world[1])
        assert run.status == "ok" and run.answer()[0] == 100 * 1024 * 1024
    finally:
        host.close()


@pytest.mark.skipif(sys.platform == "win32", reason="the watchdog runs on Linux and macOS")
def test_memory_reserved_but_never_touched_does_not_count(world: tuple[Any, Any]) -> None:
    """Resident memory, not address space: a 2 GB NumPy array that is allocated and never written
    stays far below a 300 MB limit (RLIMIT_AS, the 0.8 limit on Linux, refused it). A first
    version used a shared anonymous ``mmap``; on GitHub's Linux runners its runner reached 340 to
    352 MB resident (2026-11-13), so that call is not a clean untouched reservation there."""
    host = make_host(world, memory_mb=300)
    try:
        run = host.run(
            "import numpy as np\nx = np.empty(2 * 1024 ** 3, dtype=np.uint8)\nresult = int(x.size)",
            world[1],
        )
        assert run.status == "ok" and run.answer()[0] == 2 * 1024**3, (run.error, run.stderr)
    finally:
        host.close()


@pytest.mark.parametrize(
    ("platform", "psutil_available", "expected"),
    [
        ("win32", True, "job_object"),
        ("win32", False, "job_object"),
        ("linux", True, "rss_watchdog"),
        ("darwin", True, "rss_watchdog"),
        ("linux", False, "address_space"),
        ("darwin", False, "none"),
    ],
)
def test_how_the_memory_limit_is_enforced(
    platform: str, psutil_available: bool, expected: str
) -> None:
    assert memory_enforcement(platform, psutil_available=psutil_available) == expected


def test_without_a_limit_nothing_is_enforced(world: tuple[Any, Any]) -> None:
    host = make_host(world, memory_mb=None)
    assert host.describe()["memory_limit_mb"] is None
    assert host.describe()["memory_enforcement"] == "none"


class _GoneWorker:
    def __init__(self, stderr: str, exceeded: int | None) -> None:
        self._stderr = stderr
        self.watchdog = SimpleNamespace(exceeded=exceeded) if exceeded is not None else None

    def stderr_tail(self) -> str:
        return self._stderr


@pytest.mark.parametrize(
    ("stderr", "exceeded", "status", "error"),
    [
        ("", 412 * 1024 * 1024, "memory", "412 MB resident, over the 300 MB limit; stopped by"),
        (f"{MEMORY_MARK}: 350 MB resident", None, "memory", "(memory limit)"),
        ("MemoryError", None, "memory", "(memory limit)"),
        ("Segmentation fault", None, "error", "the process ended without a reply"),
    ],
)
def test_a_lost_process_is_classified_by_what_stopped_it(
    world: tuple[Any, Any], stderr: str, exceeded: int | None, status: str, error: str
) -> None:
    host = make_host(world, memory_mb=300)
    run = host._lost(_GoneWorker(stderr, exceeded), seconds=1.0)  # type: ignore[arg-type]
    assert run.status == status and error in run.error
    if status == "error":
        assert "memory" not in run.error


def test_a_write_outside_the_working_directory_is_blocked_and_recorded(
    world: tuple[Any, Any], tmp_path: Path
) -> None:
    target = tmp_path / "escaped.txt"
    host = make_host(world)
    try:
        run = host.run(f"open({str(target)!r}, 'w').write('x')", world[1])
        assert run.status == "unsupported" and "writing" in run.violations[0]
        assert not target.exists()
        inside = host.run("open('mine.txt', 'w').write('x')\nresult = 1", world[1])
        assert inside.status == "ok"
    finally:
        host.close()


def test_a_read_outside_the_data_is_blocked_and_recorded(
    world: tuple[Any, Any], tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    host = make_host(world)
    try:
        run = host.run(f"result = open({str(secret)!r}).read()", world[1])
        assert run.status == "unsupported" and "reading" in run.violations[0]
        assert run.answer()[0] != "private"
    finally:
        host.close()


def test_network_and_new_processes_are_blocked(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        net = host.run("import socket\ns = socket.socket()\ns.connect(('127.0.0.1', 9))", world[1])
        assert net.status == "unsupported" and "network" in net.violations[0]
        proc = host.run("import subprocess\nsubprocess.run(['python', '-c', '1'])", world[1])
        assert proc.status == "unsupported" and "process" in proc.violations[0]
    finally:
        host.close()


def test_the_environment_is_scrubbed(
    world: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    host = make_host(world)
    try:
        run = host.run(
            "import os\nresult = {'key': os.environ.get('OPENAI_API_KEY'), 'n': len(os.environ)}",
            world[1],
        )
        assert run.answer()[0]["key"] is None
    finally:
        host.close()


def test_reusing_a_process_gives_each_run_its_own_namespace_and_directory(
    world: tuple[Any, Any],
) -> None:
    host = make_host(world, reuse=10)
    try:
        first = host.run("import os\nleft = 1\nresult = [os.getpid(), os.getcwd()]", world[1])
        second = host.run(
            "import os\nresult = ['left' in globals(), os.getpid(), os.getcwd()]", world[1]
        )
        assert first.answer()[0][0] == second.answer()[0][1]  # the same process
        assert second.answer()[0][0] is False  # a fresh namespace
        assert first.answer()[0][1] != second.answer()[0][2]  # a fresh directory
        assert "one process" not in host.describe()["isolation"]
        assert host.describe()["isolation"] == "process reused for 10 runs"
    finally:
        host.close()


def test_each_run_has_its_own_process_by_default(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        pids = {host.run("import os\nresult = os.getpid()", world[1]).answer()[0] for _ in range(2)}
        assert len(pids) == 2 and host.describe()["isolation"] == "process per run"
    finally:
        host.close()


def test_the_static_scan_flags_what_the_host_cannot_decide(tmp_path: Path) -> None:
    files = {"t.csv"}
    assert scan_program("import requests\nrequests.get('http://x')", files).unsupported
    assert scan_program("import subprocess", files).unsupported
    assert scan_program("import pandas as pd\npd.read_csv('/etc/passwd')", files).unsupported
    assert scan_program("import pandas as pd\npd.read_csv('other.csv')", files).unsupported
    assert scan_program("import pandas as pd\npd.read_csv('../t.csv')", files).unsupported
    assert scan_program("open('out.txt', 'w')", files).unsupported == []
    assert scan_program("import pandas as pd\npd.read_csv('t.csv')", files).files_read == ["t.csv"]
    flagged = scan_program("import random\nrandom.random()", files)
    assert any("random" in f for f in flagged.flags)
    assert scan_program("df.sample(5)", files).flags
    assert scan_program("df.sample(5, random_state=0)", files).flags == []
    assert scan_program("import time\ntime.time()", files).flags
    assert scan_program("pd.read_csv(name)", files).flags
    assert scan_program("def (:", files).syntax_error


def test_a_final_answer_typed_as_a_literal_cannot_be_replayed(tmp_path: Path) -> None:
    files = {"t.csv"}
    read = 'import pandas as pd\nm = pd.read_csv("t.csv")["a"].mean()\n'
    typed = scan_program(read + 'final_answer("@m[2.00]")', files)
    assert any("literal the agent typed" in reason for reason in typed.unsupported)
    assert scan_program(read + 'final_answer(f"@m[2.00]")', files).unsupported
    assert scan_program(read + 'final_answer("@m[" + "2.00" + "]")', files).unsupported
    assert not scan_program(read + 'final_answer(f"@m[{m:.2f}]")', files).unsupported
    assert not scan_program(read + 'final_answer("@m[" + str(m) + "]")', files).unsupported
    assert not scan_program(read + "final_answer(m)", files).unsupported
    assert not scan_program(read + "print(m)", files).unsupported  # no final_answer at all
    mixed = scan_program(read + 'final_answer("@m[2.00]")\nfinal_answer(m)', files)
    assert not mixed.unsupported  # one call depends on the data


def test_opening_the_null_device_is_not_a_violation(world: tuple[Any, Any]) -> None:
    host = make_host(world)
    try:
        run = host.run("import os\nopen(os.devnull, 'w').write('x')\nresult = 1", world[1])
        assert run.status == "ok" and run.violations == []
    finally:
        host.close()


def test_a_blocked_operation_that_the_program_survives_is_recorded_not_rejected(
    world: tuple[Any, Any],
) -> None:
    host = make_host(world)
    try:
        code = (
            "import subprocess\n"
            "try:\n    subprocess.run(['python', '-c', '1'])\nexcept PermissionError:\n    pass\n"
            "result = 5"
        )
        run = host.run(code, world[1])
        assert run.status == "ok" and run.answer()[0] == 5 and "process" in run.violations[0]
    finally:
        host.close()
