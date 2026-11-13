# Proposed fixture: pending owner review (written by Claude; never run against a PrestoDB server).
"""A connection function for PrestoDB, for ``--confirm connection`` and ``prestodb/smoke.py``.

Uses the ``presto-python-client`` package (``pip install presto-python-client``), which provides the
``prestodb`` module. Settings come from environment variables only: ``PRESTODB_HOST``,
``PRESTODB_PORT`` (default 8080), ``PRESTODB_USER``, ``PRESTODB_CATALOG``, ``PRESTODB_SCHEMA``.
Add authentication the way your deployment needs it; never write a password into this file.

The contract: return ``(column names, rows)``; raise any exception for an error of the query; raise
``OSError`` (``ConnectionError``) when the server cannot be reached, so the finding stays
unconfirmed instead of being read as the query's own error.
"""

from __future__ import annotations

import os
from typing import Any


def run(sql: str) -> tuple[list[str], list[list[Any]]]:
    import prestodb  # the presto-python-client package

    try:
        connection = prestodb.dbapi.connect(
            host=os.environ["PRESTODB_HOST"],
            port=int(os.environ.get("PRESTODB_PORT", "8080")),
            user=os.environ["PRESTODB_USER"],
            catalog=os.environ.get("PRESTODB_CATALOG", "memory"),
            schema=os.environ.get("PRESTODB_SCHEMA", "default"),
        )
    except Exception as error:  # cannot reach the server: not the query's error
        raise ConnectionError(f"cannot connect to PrestoDB: {error}") from error
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        names = [d[0] for d in cursor.description or []]
        return names, [list(r) for r in rows]
    finally:
        connection.close()
