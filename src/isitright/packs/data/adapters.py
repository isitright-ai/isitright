"""The narrow interface between isitright and a data-analysis agent framework.

Everything framework-specific sits behind `DataAgent.solve`: given a question and a directory with
the world's data files, return the code the agent executed and the answer it gave. The audit never
imports a framework. `PandasAIAgent` and `SmolagentsAgent` import theirs inside `solve`, so they
can be tried with fakes where the framework is not installed.

An agent's code is untrusted. `SubprocessAgent` runs any `DataAgent` in a separate process with a
scrubbed environment that passes through only the named variables (the model's API key), a timeout
and the host's memory limit; the audit process never executes what a model wrote.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from isitright.packs.data.host import RunResult, UntrustedCodeError, _Limits, scrubbed_environment
from isitright.packs.data.programs import ProgramSource, RecordedProgram

AGENT_RUNNER = Path(__file__).with_name("_agent_runner.py")


def load_env_file(path: Path, names: list[str]) -> None:
    """Set the named variables from a dotenv-style file unless the environment already has them.

    Only the names asked for are read (the ones passed to the agent); other lines are ignored and
    no value is ever printed. Quotes around a value and a leading ``export`` are removed.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip().removeprefix("export ").strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key, value = key.strip(), value.strip()
        if key in names and not os.environ.get(key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ[key] = value


def unset_names(names: list[str]) -> list[str]:
    """The variables among ``names`` that the environment does not have (or has empty)."""
    return [name for name in names if not os.environ.get(name)]


@dataclass(frozen=True)
class AgentRun:
    """One attempt: the code executed (all steps joined, replayable), the answer and the cost."""

    code: str
    answer: Any
    input_tokens: int = 0
    output_tokens: int = 0
    money: float | None = None
    error: str | None = None
    library_versions: dict[str, str] | None = None


class DataAgent(Protocol):
    name: str
    model: str

    def solve(self, question: str, directory: Path) -> AgentRun: ...


def _dataset_prelude(directory: Path, names: dict[str, str]) -> str:
    """Python that makes SQL-style access work outside PandasAI: `execute_sql_query` over DuckDB,
    with each file registered under the dataset name PandasAI used."""
    lines = ["import duckdb", "import pandas as pd", "_con = duckdb.connect()", "dfs = []"]
    for file, name in names.items():
        lines.append(f"dfs.append(pd.read_csv({file!r}))")
        lines.append(f"_con.register({name!r}, dfs[-1])")
    lines += ["def execute_sql_query(query):", "    return _con.sql(query).df()", ""]
    return "\n".join(lines)


class PandasAIAgent:
    """PandasAI 3 (`pandasai.Agent`). The generated code calls `execute_sql_query` and sets
    `result`; the recorded program prepends a prelude that defines both inputs, so it replays
    without PandasAI. PandasAI 3.0.0 pins pandas<3 and Python<3.12: use a separate environment."""

    name = "pandasai"

    def __init__(self, model: str = "", llm: Any = None) -> None:
        self.model = model
        self._llm = llm  # PandasAI does not report token counts, so it reports no cost

    def solve(self, question: str, directory: Path) -> AgentRun:
        import pandasai as pai

        if self._llm is not None:
            pai.config.set({"llm": self._llm})
        files = sorted(p for p in directory.iterdir() if p.suffix == ".csv")
        frames = [pai.read_csv(str(p)) for p in files]
        names = {
            p.name: getattr(getattr(f, "schema", None), "name", p.stem)
            for p, f in zip(files, frames, strict=True)
        }
        agent = pai.Agent(frames)
        response = agent.chat(question)
        code = agent.last_code_executed or ""
        return AgentRun(
            code=_dataset_prelude(directory, names) + code,
            answer=getattr(response, "value", response),
            library_versions={"pandasai": str(getattr(pai, "__version__", ""))},
        )


class SmolagentsAgent:
    """smolagents `CodeAgent`. Each step's `code_action` is joined in order; `final_answer(...)`
    is provided by the host when the program is replayed."""

    name = "smolagents"

    def __init__(
        self,
        model: str = "",
        model_object: Any = None,
        imports: tuple[str, ...] = (),
        usd_per_million_tokens: tuple[float, float] | list[float] | None = None,
    ) -> None:
        """``usd_per_million_tokens`` is (input, output); with it the run reports its cost, which a
        money budget needs."""
        self.model = model
        self._model_object = model_object
        self._prices = tuple(usd_per_million_tokens) if usd_per_million_tokens else None
        self._imports = imports or ("pandas", "numpy", "scipy", "statistics", "math")

    def solve(self, question: str, directory: Path) -> AgentRun:
        from smolagents import CodeAgent
        from smolagents.memory import ActionStep

        model = self._model_object or self._default_model()
        agent = CodeAgent(tools=[], model=model, additional_authorized_imports=list(self._imports))
        files = ", ".join(sorted(p.name for p in directory.iterdir()))
        answer = agent.run(
            f"{question}\n\nThe data files are in the current working directory: {files}. "
            "Read them with pandas. Give the final answer with final_answer(...)."
        )
        code = "\n\n".join(
            step.code_action
            for step in agent.memory.steps
            if isinstance(step, ActionStep) and step.code_action
        )
        monitor = getattr(agent, "monitor", None)
        tokens_in = int(getattr(monitor, "total_input_token_count", 0) or 0)
        tokens_out = int(getattr(monitor, "total_output_token_count", 0) or 0)
        money = (
            (tokens_in * self._prices[0] + tokens_out * self._prices[1]) / 1_000_000
            if self._prices
            else None
        )
        return AgentRun(
            code=code, answer=answer, input_tokens=tokens_in, output_tokens=tokens_out, money=money
        )

    def _default_model(self) -> Any:
        from smolagents import OpenAIServerModel

        extra: dict[str, Any] = {}
        try:
            # Newer OpenAI models reject the `stop` parameter that CodeAgent sends; smolagents
            # drops it when told to and cuts the reply at the stop sequences itself.
            from smolagents.models import REMOVE_PARAMETER

            extra["stop"] = REMOVE_PARAMETER
        except ImportError:  # a smolagents without it (or a test double): send the default
            pass
        return OpenAIServerModel(
            model_id=self.model or os.environ["ISITRIGHT_MODEL"],
            api_key=os.environ["OPENAI_API_KEY"],
            **extra,
        )


class SubprocessAgent:
    """Runs a `DataAgent` factory (``module:callable``) in a separate process per attempt."""

    def __init__(
        self,
        factory: str,
        *,
        trust_code: bool = False,
        pass_env: tuple[str, ...] = (),
        timeout_seconds: float = 600.0,
        memory_mb: int | None = 4096,
        kwargs: dict[str, Any] | None = None,
        name: str = "",
        model: str = "",
    ) -> None:
        self.factory, self.pass_env = factory, pass_env
        self.trust_code, self.timeout_seconds = trust_code, timeout_seconds
        self.memory_mb, self.kwargs = memory_mb, kwargs or {}
        self.name, self.model = name or factory, model

    def solve(self, question: str, directory: Path) -> AgentRun:
        if not self.trust_code:
            raise UntrustedCodeError(
                "running an agent executes model-written code; pass --trust-code"
            )
        root = Path(tempfile.mkdtemp(prefix="isitright-agent-"))
        try:
            work = root / "work"
            shutil.copytree(directory, work)
            request = {
                "factory": self.factory,
                "kwargs": self.kwargs,
                "question": question,
                "work": str(work),
                "result": str(root / "result.json"),
            }
            (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
            env = scrubbed_environment(root)
            env.update({n: os.environ[n] for n in self.pass_env if n in os.environ})
            limits = _Limits(self.memory_mb * 1024 * 1024 if self.memory_mb else None)
            process = subprocess.Popen(
                [sys.executable, "-s", "-B", str(AGENT_RUNNER), str(root / "request.json")],
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=limits.preexec() if sys.platform != "win32" else None,
            )
            limits.attach(process)
            try:
                _, err = process.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                limits.release()
                process.kill()
                process.communicate()
                return AgentRun("", None, error=f"agent timed out after {self.timeout_seconds:g} s")
            finally:
                limits.release()
            path = root / "result.json"
            if not path.is_file():
                return AgentRun(
                    "", None, error=err.decode("utf-8", "replace")[-400:] or "no result"
                )
            data = json.loads(path.read_text(encoding="utf-8"))
            return AgentRun(
                code=data.get("code", ""),
                answer=data.get("answer"),
                input_tokens=int(data.get("input_tokens", 0)),
                output_tokens=int(data.get("output_tokens", 0)),
                money=data.get("money"),
                error=data.get("error") or None,
                library_versions=data.get("library_versions"),
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


def recorded_program(
    task_id: str,
    program_id: str,
    run: AgentRun,
    agent: DataAgent,
    *,
    answer_text: str = "",
    stand_in: bool = False,
    note: str = "",
) -> RecordedProgram:
    """The recording of one agent attempt, in the format the frozen audit reads."""
    return RecordedProgram(
        task_id=task_id,
        program_id=program_id,
        code=run.code,
        answer={"text": answer_text or str(run.answer), "source": "agent"},
        source=ProgramSource(
            kind="constructed_stand_in" if stand_in else "agent",
            agent=agent.name,
            model=agent.model,
            note=note,
            library_versions=run.library_versions or {},
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        ),
    )


def run_result_answer(result: RunResult) -> Any:
    return result.answer()[0]
