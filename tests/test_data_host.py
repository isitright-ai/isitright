"""The data host: what it runs, what it limits, and what it records. Not a security boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")

from isitright.packs.data.host import DataHost, UntrustedCodeError
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


def test_a_memory_limit_stops_a_program_that_allocates_too_much(world: tuple[Any, Any]) -> None:
    host = make_host(world, memory_mb=300)
    try:
        run = host.run("x = bytearray(1500 * 1024 * 1024)\nresult = len(x)", world[1])
        assert run.status in {"memory", "error"} and run.answer()[0] != 1500 * 1024 * 1024
        assert run.status == "memory"
    finally:
        host.close()


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
