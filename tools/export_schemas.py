"""Export the checked-in report schema deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from isitright.core.evidence import AuditReport

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {ROOT / "schemas" / "report-0.5.schema.json": AuditReport.model_json_schema()}


def serialized(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero when checked-in schemas differ from the models.",
    )
    arguments = parser.parse_args()
    stale: list[Path] = []
    for path, schema in SCHEMAS.items():
        expected = serialized(schema)
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    extra = [p for p in (ROOT / "schemas").glob("*.json") if p not in SCHEMAS]
    if arguments.check and extra:
        stale.extend(p.relative_to(ROOT) for p in extra)
    if stale:
        names = ", ".join(str(path) for path in stale)
        raise SystemExit(f"report schema files are stale: {names}")


if __name__ == "__main__":
    main()
