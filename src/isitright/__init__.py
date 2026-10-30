"""isitright audits agent evals.

The core (`isitright.core`) describes worlds, perturbs them, and reports evidence. Packs apply it:
`isitright.packs.sql` for text-to-SQL programs and `isitright.packs.mcp` for tool-using agents.
"""

from isitright.__about__ import __version__
from isitright.core.evidence import SCHEMA_VERSION, AuditReport, CaseReport
from isitright.packs.sql import CheckConfig, SqlInputError, SuiteCase, check, check_suite

__all__ = [
    "SCHEMA_VERSION",
    "AuditReport",
    "CaseReport",
    "CheckConfig",
    "SqlInputError",
    "SuiteCase",
    "__version__",
    "check",
    "check_suite",
]
