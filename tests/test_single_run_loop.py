"""N1: nothing outside `SubjectRunner` executes a subject.

A subject is run with ``subject.execute(target, seed)``. Budget checks, cost records, call counts
and seeds live in `SubjectRunner.run`, so a pack that called ``execute`` itself would run outside
them.
This test walks the source tree and fails on such a call. Two forms are caught:

* a call ``<anything ending in "subject">.execute(...)``;
* a call ``<anything>.execute(target, seed)``, with a second argument named like a seed;
* a call to ``run_agent``, which starts an agent command, outside a method named ``execute``.

A call is allowed inside `SubjectRunner.run` and inside a method named ``execute`` (an adapter that
turns the runner's call into the subject's own: it is the subject, not a caller). Anything else
needs a line in ``single_run_loop_allowlist.txt`` ("path:line"). The file is empty and stays empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "isitright"
ALLOWLIST = Path(__file__).with_name("single_run_loop_allowlist.txt")


def _is_subject_call(node: ast.Call) -> bool:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
        return False
    receiver = ast.unparse(func.value)
    if receiver.rsplit(".", 1)[-1].lower().endswith("subject"):
        return True
    if len(node.args) == 2:
        second = ast.unparse(node.args[1]).lower()
        return "seed" in second
    return False


def _is_raw_agent_start(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "run_agent") or (
        isinstance(func, ast.Attribute) and func.attr == "run_agent"
    )


def _allowed_scope(stack: list[str]) -> bool:
    return stack[-1:] == ["execute"] or stack[-2:] == ["SubjectRunner", "run"]


def find_violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        def visit(node: ast.AST, stack: list[str], path: Path = path) -> None:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                stack = [*stack, node.name]
            if (
                isinstance(node, ast.Call)
                and (_is_subject_call(node) or _is_raw_agent_start(node))
                and not _allowed_scope(stack)
            ):
                found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
            for child in ast.iter_child_nodes(node):
                visit(child, stack)

        visit(tree, [])
    return found


def test_no_code_outside_the_runner_executes_a_subject() -> None:
    allowed = {
        line.strip()
        for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert allowed == set(), "the allowlist stays empty"
    assert find_violations(SRC) == []


def test_the_scan_sees_the_runner_and_the_adapters_it_allows() -> None:
    """The scan is not vacuous: it finds calls in the runner and in adapters, and allows them."""
    text = (SRC / "core" / "stochastic.py").read_text(encoding="utf-8")
    assert "self.subject.execute(target, seed)" in text
    research = (SRC / "packs" / "research" / "audit.py").read_text(encoding="utf-8")
    assert "self.subject.execute(target.world, seed)" in research


def test_the_scan_catches_a_call_made_outside_the_runner(tmp_path: Path) -> None:
    (tmp_path / "pack.py").write_text(
        "def audit(subject, world):\n    return subject.execute(world, 1)\n"
        "def other(agent, world, seed):\n    return agent.execute(world, seed)\n"
        "class Adapter:\n    def execute(self, target, seed):\n"
        "        return self.subject.execute(target, seed)\n"
        "class SubjectRunner:\n    def run(self):\n        return self.subject.execute(1, 2)\n"
        "    def other(self):\n        return self.subject.execute(1, 2)\n",
        encoding="utf-8",
    )
    assert find_violations(tmp_path) == ["pack.py:2", "pack.py:4", "pack.py:12"]


def test_starting_an_agent_outside_an_execute_method_is_caught(tmp_path: Path) -> None:
    (tmp_path / "pack.py").write_text(
        "def audit(argv):\n    return run_agent(argv)\n"
        "class Subject:\n    def execute(self, target, seed):\n        return run_agent(1)\n",
        encoding="utf-8",
    )
    assert find_violations(tmp_path) == ["pack.py:2"]


def test_a_database_cursor_is_not_a_subject(tmp_path: Path) -> None:
    (tmp_path / "db.py").write_text(
        "def q(connection, sql, params):\n    return connection.execute(sql, params)\n",
        encoding="utf-8",
    )
    assert find_violations(tmp_path) == []
