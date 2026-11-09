# Proposed fixture: pending owner review.
# Written by Claude. The rules below are mine; Spider's column descriptions are the only input.
"""Declare constraints for each task from the column descriptions in its DDL.

Usage: python -I make_constraints.py <demo directory>

Two rules, both narrow and both proposed (they never grant domain validation on their own beyond
what the owner approves):

* ``x-unique``: a column whose description calls it a unique identifier, key or number of the
  record, row, incident, entry, transaction, invoice, order, case or event, and whose name looks
  like one (``id``, ``key``, ``number``, ``no``). "Unique number assigned to the store" is not
  matched: it identifies a store, not a row of the table it appears in.
* ``minimum: 0``: an integer column whose description starts with "number of" or "count of".

Writes ``constraints/<task>.yaml`` and ``constraints_summary.json``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from isitright.packs.sql.dialects import get_dialect
from isitright.packs.sql.errors import SqlInputError
from isitright.packs.sql.warehouse_ddl import parse_warehouse_schema

UNIQUE_DESCRIPTION = re.compile(
    r"\bunique\b.*\b(record|row|incident|accident|entry|transaction|invoice|order|case|event)\b",
    re.IGNORECASE,
)
ID_NAME = re.compile(r"(^|_)(id|key|number|no)($|_)", re.IGNORECASE)
COUNT_DESCRIPTION = re.compile(r"^\s*(the\s+)?(total\s+)?(number|count)\s+of\b", re.IGNORECASE)
INTEGERS = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT"}


def main(demo: Path) -> None:
    bigquery = get_dialect("bigquery")
    out = demo / "constraints"
    out.mkdir(exist_ok=True)
    skipped: dict[str, str] = {}
    summary: dict[str, object] = {
        "unique": [],
        "non_negative": [],
        "tasks_with_rules": 0,
        "ddl_not_imported": skipped,
    }
    for ddl_file in sorted((demo / "ddl").glob("*.sql")):
        try:
            schema = parse_warehouse_schema(ddl_file.read_text(encoding="utf-8"), bigquery)
        except SqlInputError as error:  # the audit reports the same task as UNSUPPORTED
            skipped[ddl_file.stem] = str(error)
            continue
        properties: dict[str, dict[str, object]] = {}
        for table in schema.tables:
            unique: list[list[str]] = []
            columns: dict[str, dict[str, object]] = {}
            for column in table.columns:
                description = column.description or ""
                if (
                    UNIQUE_DESCRIPTION.search(description)
                    and ID_NAME.search(column.name)
                    and column.type_tree is not None
                    and not column.type_tree.nested
                ):
                    unique.append([column.name])
                    summary["unique"].append(f"{ddl_file.stem}:{table.name}.{column.name}")  # type: ignore[union-attr]
                if column.declared_type in INTEGERS and COUNT_DESCRIPTION.search(description):
                    columns[column.name] = {"minimum": 0}
                    summary["non_negative"].append(f"{ddl_file.stem}:{table.name}.{column.name}")  # type: ignore[union-attr]
            entry: dict[str, object] = {}
            if unique:
                entry["x-unique"] = unique
            if columns:
                entry["items"] = {"properties": columns}
            if entry:
                properties[table.name] = entry
        target = out / f"{ddl_file.stem}.yaml"
        if properties:
            header = (
                "# Proposed fixture: pending owner review (declared from column descriptions)\n"
            )
            target.write_text(header + yaml.safe_dump({"properties": properties}), encoding="utf-8")
            summary["tasks_with_rules"] = int(summary["tasks_with_rules"]) + 1  # type: ignore[call-overload]
        elif target.exists():
            target.unlink()
    (demo / "constraints_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{summary['tasks_with_rules']} tasks with rules; "
        f"{len(summary['unique'])} unique, {len(summary['non_negative'])} non-negative"  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
