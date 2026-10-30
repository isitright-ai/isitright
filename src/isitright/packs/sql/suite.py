"""JSONL suite contract loading without executing cases."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from isitright.packs.sql.models import SuiteCase


class SuiteInputError(ValueError):
    """A suite record is not valid under the v0.1 input contract."""


def parse_suite_lines(lines: Iterable[str]) -> list[SuiteCase]:
    """Parse nonblank JSONL records and report their one-based line numbers."""
    cases: list[SuiteCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            case = SuiteCase.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as error:
            raise SuiteInputError(f"invalid suite record on line {line_number}: {error}") from error
        if case.case_id in seen_ids:
            raise SuiteInputError(f"duplicate case_id {case.case_id!r} on line {line_number}")
        seen_ids.add(case.case_id)
        cases.append(case)
    return cases


def load_suite_cases(path: str | Path) -> list[SuiteCase]:
    """Load a UTF-8 JSONL suite under the Stage 0 input contract."""
    with Path(path).open(encoding="utf-8") as suite_file:
        return parse_suite_lines(suite_file)
