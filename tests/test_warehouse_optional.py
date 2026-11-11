"""The warehouse clients are optional: nothing imports them until a native host needs one."""

from __future__ import annotations

import subprocess
import sys

import pytest

from isitright.packs.sql import BigQueryHost, TrinoHost
from isitright.packs.sql.errors import SqlInputError

BLOCK = (
    "import sys\n"
    "for name in ('google', 'google.cloud', 'google.cloud.bigquery', 'trino', 'trino.dbapi'):\n"
    "    sys.modules[name] = None\n"
)


def test_the_package_and_every_pack_import_without_the_warehouse_clients() -> None:
    code = BLOCK + (
        "import isitright\n"
        "import isitright.packs.sql, isitright.packs.sql.native\n"
        "import isitright.packs.mcp, isitright.packs.data\n"
        "from isitright.cli import app\n"
        "print('ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_the_hosts_say_which_extra_to_install_when_a_client_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("google", "google.cloud", "google.cloud.bigquery", "trino", "trino.dbapi"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(SqlInputError, match=r"isitright\[bigquery\]"):
        BigQueryHost()._client_now()
    with pytest.raises(SqlInputError, match=r"isitright\[trino\]"):
        TrinoHost()._connection()
