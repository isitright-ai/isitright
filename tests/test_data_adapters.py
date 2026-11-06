"""Framework adapters against fakes (no key, no network), and the subprocess boundary."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pandas")
duckdb = pytest.importorskip("duckdb")  # the PandasAI prelude queries DuckDB

from isitright.packs.data.adapters import (  # noqa: E402
    AgentRun,
    PandasAIAgent,
    SmolagentsAgent,
    SubprocessAgent,
    recorded_program,
)
from isitright.packs.data.audit import AuditConfig, DataAudit  # noqa: E402
from isitright.packs.data.host import DataHost, UntrustedCodeError  # noqa: E402
from isitright.packs.data.programs import load_programs, write_programs  # noqa: E402
from isitright.packs.data.task import load_task  # noqa: E402
from tests.data_factories import ORDERS, make_task  # noqa: E402

ROOT = Path(__file__).parents[1]


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    path = tmp_path / "world"
    path.mkdir()
    (path / "orders.csv").write_text(ORDERS, encoding="utf-8")
    return path


def fake_pandasai(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("pandasai")
    module.__version__ = "3.0.0"  # type: ignore[attr-defined]

    class Frame:
        def __init__(self, name: str) -> None:
            self.schema = types.SimpleNamespace(name=name)

    class Agent:
        def __init__(self, frames: list[Frame]) -> None:
            self.frames = frames
            self.last_code_executed = (
                'df = execute_sql_query("SELECT AVG(amount) AS m FROM orders '
                "WHERE region = 'north'\")\n"
                "result = {'type': 'number', 'value': float(df['m'][0])}\n"
            )

        def chat(self, question: str) -> Any:
            return types.SimpleNamespace(value=23.33)

    module.read_csv = lambda path: Frame(Path(path).stem)  # type: ignore[attr-defined]
    module.Agent = Agent  # type: ignore[attr-defined]
    module.config = types.SimpleNamespace(set=lambda values: None)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pandasai", module)


def test_the_pandasai_adapter_records_a_program_that_replays_without_pandasai(
    monkeypatch: pytest.MonkeyPatch, directory: Path, tmp_path: Path
) -> None:
    fake_pandasai(monkeypatch)
    agent = PandasAIAgent(model="fake-model")
    run = agent.solve("Mean amount of north?", directory)
    assert run.answer == 23.33 and "execute_sql_query" in run.code
    assert run.library_versions == {"pandasai": "3.0.0"}
    task = load_task(make_task(tmp_path / "task"))
    with DataAudit(task, AuditConfig(trust_code=True, timeout_seconds=30.0)) as audit:
        replay = audit.host.run(run.code, audit.prepared.base)
        assert replay.status == "ok", replay.error
        assert audit.comparator.compare({"north_mean": 23.33}, replay.answer()[0]).matches
    recording = recorded_program("orders", "pandasai-1", run, agent)
    write_programs(tmp_path / "p.jsonl", [recording])
    loaded = load_programs(tmp_path / "p.jsonl")[0]
    assert loaded.source.kind == "agent" and loaded.source.agent == "pandasai"
    assert loaded.source.model == "fake-model" and loaded.digest == recording.digest


def fake_smolagents(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = types.ModuleType("smolagents.memory")

    class ActionStep:
        def __init__(self, code: str | None) -> None:
            self.code_action = code

    class Other:
        code_action = "ignored = True"

    memory.ActionStep = ActionStep  # type: ignore[attr-defined]
    module = types.ModuleType("smolagents")

    class CodeAgent:
        def __init__(self, tools: list[Any], model: Any, additional_authorized_imports: list[str]):
            self.imports = additional_authorized_imports
            self.monitor = types.SimpleNamespace(
                total_input_token_count=120, total_output_token_count=30
            )
            self.memory = types.SimpleNamespace(
                steps=[
                    Other(),
                    ActionStep("import pandas as pd"),
                    ActionStep(None),
                    ActionStep("final_answer(1)"),
                ]
            )

        def run(self, prompt: str) -> Any:
            assert "orders.csv" in prompt
            return 1

    module.CodeAgent = CodeAgent  # type: ignore[attr-defined]
    module.OpenAIServerModel = lambda **kw: kw  # type: ignore[attr-defined]
    module.memory = memory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "smolagents", module)
    monkeypatch.setitem(sys.modules, "smolagents.memory", memory)


def test_the_smolagents_adapter_joins_the_executed_code_and_counts_tokens(
    monkeypatch: pytest.MonkeyPatch, directory: Path
) -> None:
    fake_smolagents(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    run = SmolagentsAgent(model="fake").solve("question", directory)
    assert run.code == "import pandas as pd\n\nfinal_answer(1)"
    assert (run.input_tokens, run.output_tokens, run.answer) == (120, 30, 1)
    host = DataHost(_schema(directory), trust_code=True)
    try:
        replay = host.run_directory(run.code, directory)
        assert replay.answer() == (1, "final_answer")  # the host provides final_answer
    finally:
        host.close()


def _schema(directory: Path):
    from isitright.packs.data.mapping import TableFile, read_frame, schema_from_frames

    frames = {"orders": read_frame(directory / "orders.csv")}
    return schema_from_frames(frames, [TableFile("orders.csv", "orders")])


def test_a_subprocess_agent_sees_only_the_variables_it_is_given(
    monkeypatch: pytest.MonkeyPatch, directory: Path
) -> None:
    monkeypatch.setenv("ISITRIGHT_TEST_KEY", "allowed-value")
    monkeypatch.setenv("ISITRIGHT_TEST_OTHER", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    agent = SubprocessAgent(
        "tests.data_agents:probe",
        trust_code=True,
        pass_env=("ISITRIGHT_TEST_KEY", "PYTHONPATH"),
        timeout_seconds=60.0,
    )
    run = agent.solve("q", directory)
    assert run.error is None, run.error
    assert "allowed-value" in str(run.answer) and "must-not-leak" not in str(run.answer)
    assert "'orders.csv'" in str(run.answer)
    assert (run.input_tokens, run.output_tokens) == (1, 1)


def test_a_subprocess_agent_reports_a_factory_that_fails_and_refuses_without_trust(
    monkeypatch: pytest.MonkeyPatch, directory: Path
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    failing = SubprocessAgent(
        "tests.data_agents:failing", trust_code=True, pass_env=("PYTHONPATH",), timeout_seconds=60.0
    )
    run = failing.solve("q", directory)
    assert run.error and "could not build" in run.error
    with pytest.raises(UntrustedCodeError):
        SubprocessAgent("tests.data_agents:probe").solve("q", directory)


def test_a_subprocess_agent_that_runs_too_long_is_stopped(
    monkeypatch: pytest.MonkeyPatch, directory: Path
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    slow = SubprocessAgent(
        "tests.data_agents:probe", trust_code=True, pass_env=("PYTHONPATH",), timeout_seconds=0.05
    )
    run = slow.solve("q", directory)
    assert run.error and "timed out" in run.error
    assert isinstance(run, AgentRun)


def _capture_module():
    import importlib.util

    path = ROOT / "examples" / "data" / "dabench" / "capture.py"
    spec = importlib.util.spec_from_file_location("capture_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_capture_script_spends_nothing_without_confirm_and_records_programs_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_task(tmp_path / "tasks" / "orders")
    capture = _capture_module()
    base = [
        "capture.py",
        str(tmp_path / "tasks"),
        "--agent",
        "tests.data_agents:csv_agent",
        "--output",
        str(tmp_path / "programs.jsonl"),
        "--pass-env",
        "PYTHONPATH",
    ]
    monkeypatch.setattr(sys, "argv", base)
    assert capture.main() == 0
    assert "Not run" in capsys.readouterr().out and not (tmp_path / "programs.jsonl").exists()
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setattr(sys, "argv", [*base, "--confirm"])
    assert capture.main() == 0
    out = capsys.readouterr().out
    assert "MATCHES_GOLD" in out and "isitright data check" in out
    recorded = load_programs(tmp_path / "programs.jsonl")
    assert [(p.task_id, p.program_id, p.source.kind) for p in recorded] == [
        ("orders", "run-1", "agent")
    ]


def _capture_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "capture.py",
        str(tmp_path / "tasks"),
        "--agent",
        "tests.data_agents:priced_agent",
        "--output",
        str(tmp_path / "programs.jsonl"),
        "--pass-env",
        "PYTHONPATH",
        "--confirm",
        *extra,
    ]


def test_the_capture_script_stops_at_the_money_cap_and_keeps_what_it_captured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_task(tmp_path / "tasks" / "orders")
    capture = _capture_module()
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    prices = '{"usd_per_million_tokens": [3.0, 0.0]}'  # 100,000 input tokens: 0.30 USD per run
    argv = _capture_args(tmp_path, "--runs", "5", "--max-money", "0.5", "--agent-kwargs", prices)
    monkeypatch.setattr(sys, "argv", argv)
    assert capture.main() == 0
    out = capsys.readouterr().out
    assert "Stopped early: cost cap reached" in out and "0.6000 USD" in out
    recorded = load_programs(tmp_path / "programs.jsonl")
    assert [p.program_id for p in recorded] == ["run-1", "run-2"]  # the cap came before run 3


def test_a_money_cap_needs_prices_and_nothing_is_called_without_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_task(tmp_path / "tasks" / "orders")
    capture = _capture_module()
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setattr(sys, "argv", _capture_args(tmp_path, "--max-money", "5"))
    assert capture.main() == 2
    assert "usd_per_million_tokens" in capsys.readouterr().err
    assert not (tmp_path / "programs.jsonl").exists()


def test_a_variable_that_is_not_set_stops_the_capture_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_task(tmp_path / "tasks" / "orders")
    capture = _capture_module()
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.delenv("ISITRIGHT_TEST_KEY", raising=False)
    argv = _capture_args(tmp_path, "--pass-env", "ISITRIGHT_TEST_KEY")
    monkeypatch.setattr(sys, "argv", argv)
    assert capture.main() == 2
    assert "ISITRIGHT_TEST_KEY" in capsys.readouterr().err
    assert not (tmp_path / "programs.jsonl").exists()


def test_the_env_file_supplies_only_the_named_variables_and_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _capture_module()
    for name in ("ISITRIGHT_TEST_A", "ISITRIGHT_TEST_B", "ISITRIGHT_TEST_C"):
        monkeypatch.setenv(name, "")  # so the test leaves nothing behind
    monkeypatch.setenv("ISITRIGHT_TEST_B", "from-the-environment")
    env_file = tmp_path / "keys.env"
    env_file.write_text(
        "# a comment\n"
        'ISITRIGHT_TEST_A="secret value"\n'
        "export ISITRIGHT_TEST_B=from-the-file\n"
        "ISITRIGHT_TEST_C=not-asked-for\n"
        "not a variable line\n",
        encoding="utf-8",
    )
    capture.load_env_file(env_file, ["ISITRIGHT_TEST_A", "ISITRIGHT_TEST_B"])
    assert os.environ["ISITRIGHT_TEST_A"] == "secret value"  # quotes removed
    assert os.environ["ISITRIGHT_TEST_B"] == "from-the-environment"  # the environment wins
    assert os.environ["ISITRIGHT_TEST_C"] == ""  # not named, so not read
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_a_failed_step_is_guarded_so_the_replay_does_what_the_agent_did() -> None:
    from isitright.packs.data.adapters import join_steps

    steps = [
        ("rows = [1, 2, 3]\nvalue = rows[10]", True),  # raised IndexError after defining rows
        ("this is not python (", True),  # never ran, so it is left out
        ("total = sum(rows)\nfinal_answer(total)", False),
    ]
    program = join_steps(steps)
    assert "this is not python" not in program
    assert "try:" in program and "except Exception:" in program
    answers: list[Any] = []
    exec(compile(program, "<program>", "exec"), {"final_answer": answers.append})
    assert answers == [6]  # `rows` survived the failed step, and the replay did not stop there
    assert join_steps([("x = 1", False), ("y = 2", False)]) == "x = 1\n\ny = 2"
