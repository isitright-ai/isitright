"""The child process of `SubprocessAgent`: imports the factory, runs one attempt, writes JSON.

Run as ``python -s -B _agent_runner.py <request.json>``. The agent framework and the model-written
code it executes live in this process, never in the audit process.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import traceback


def main(request_path: str) -> int:
    sys.path[:] = [
        p
        for p in sys.path
        if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))
    ]
    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)
    os.chdir(request["work"])
    sys.path.insert(0, request["work"])
    result: dict[str, object]
    try:
        module_name, _, attribute = request["factory"].partition(":")
        factory = getattr(importlib.import_module(module_name), attribute)
        agent = factory(**request.get("kwargs", {}))
        from pathlib import Path

        run = agent.solve(request["question"], Path(request["work"]))
        answer = run.answer
        result = {
            "code": run.code,
            "answer": answer
            if isinstance(answer, str | int | float | bool | type(None))
            else repr(answer),
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "money": run.money,
            "error": run.error,
            "library_versions": run.library_versions,
        }
    except BaseException as error:
        result = {
            "code": "",
            "answer": None,
            "error": "".join(traceback.format_exception_only(type(error), error))[-400:],
        }
    with open(request["result"], "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
