"""Scripted data agents for tests: deterministic stand-ins, not real agents.

They write a program (their "tool call"), run it with the host the way a framework's code tool
would, and answer with its output. Used offline, with no model and no network.
"""

from __future__ import annotations

from pathlib import Path

from isitright.packs.data.adapters import AgentRun
from isitright.packs.data.host import DataHost


class FixedProgramAgent:
    """Always writes the same program."""

    name = "scripted-fixed"
    model = "none"

    def __init__(self, host: DataHost, code: str) -> None:
        self.host, self.code = host, code
        self.calls = 0

    def solve(self, question: str, directory: Path) -> AgentRun:
        self.calls += 1
        run = self.host.run_directory(self.code, directory)
        return AgentRun(code=self.code, answer=run.answer()[0], input_tokens=100, output_tokens=20)


class BrokenAgent:
    name = "scripted-broken"
    model = "none"

    def solve(self, question: str, directory: Path) -> AgentRun:
        return AgentRun(code="", answer=None, error="the model returned no code")


class EnvironmentProbe:
    """Runs in a child process: reports which environment variables the child can see."""

    name = "probe"
    model = "none"

    def solve(self, question: str, directory: Path) -> AgentRun:
        import os

        seen = {
            "allowed": os.environ.get("ISITRIGHT_TEST_KEY"),
            "other": os.environ.get("ISITRIGHT_TEST_OTHER"),
            "cwd_files": sorted(p.name for p in directory.iterdir()),
        }
        return AgentRun(code="# probe", answer=repr(seen), input_tokens=1, output_tokens=1)


def probe() -> EnvironmentProbe:
    return EnvironmentProbe()


def failing() -> BrokenAgent:
    raise RuntimeError("the factory could not build the agent")


class CsvAgent:
    """Computes the north mean with the csv module, skipping blanks (the right way)."""

    name = "csv-agent"
    model = "none"

    def solve(self, question: str, directory: Path) -> AgentRun:
        import csv

        with (directory / "orders.csv").open(encoding="utf-8", newline="") as handle:
            values = [
                float(r["amount"])
                for r in csv.DictReader(handle)
                if r["region"] == "north" and r["amount"]
            ]
        mean = sum(values) / len(values) if values else float("nan")
        return AgentRun(
            code="# csv agent", answer=f"@north_mean[{mean:.2f}]", input_tokens=5, output_tokens=5
        )


def csv_agent() -> CsvAgent:
    return CsvAgent()
