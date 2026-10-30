"""Create the toy SQLite database used by the examples.

Usage:
    python examples/sqlite/create_database.py example.sqlite
    python examples/sqlite/create_database.py empty.sqlite --schema-only
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the toy SQLite database.")
    parser.add_argument("database", type=Path, help="SQLite file to create")
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="create the tables without rows; isitright then synthesizes its own states",
    )
    args = parser.parse_args()
    if args.database.exists():
        parser.error(f"{args.database} already exists")
    connection = sqlite3.connect(args.database)
    try:
        connection.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
        if not args.schema_only:
            connection.executescript((HERE / "seed.sql").read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    print(f"Created {args.database}")


if __name__ == "__main__":
    main()
