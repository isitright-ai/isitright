# Proposed fixture: pending owner review
"""A proposer for the shop scenario that returns a recorded model response (no key, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "examples" / "proposers"))

from model_proposer import ModelHintProposer  # noqa: E402

RECORDED = (HERE / "shop_response.txt").read_text(encoding="utf-8")
PROPOSER = ModelHintProposer(complete=lambda prompt: RECORDED)
