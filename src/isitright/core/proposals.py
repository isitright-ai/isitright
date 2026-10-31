"""LLM-proposed hints: the plumbing, not a model client.

A `HintProposer` reads the task text, the policy text and the tool schemas and returns hints. Every
hint it returns is labeled `proposed`; nothing here calls a model, reads a key or needs a network.
The flow is:

1. ``propose_hints`` runs a proposer and checks each hint against the entity model (a hint that
   does not resolve is rejected with the reason, not guessed).
2. ``write_proposals`` puts the result in a YAML file. The owner edits it.
3. ``confirm_proposals`` marks hints ``confirmed`` (all, or by name). A confirmed hint is loaded as
   ``declared``; one still ``proposed`` is loaded as ``proposed``; a ``rejected`` one is dropped.

A proposed hint prioritizes the search and is listed in the report with the worlds it led to. It
never grants a validity tier: the tiers come from constraints, reachability, the task's declared
lookups and observability, and a proposed lookup does not count as a declared one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml  # type: ignore[import-untyped]

from isitright.core.entities import EntitySchema, ModelError
from isitright.core.hints import Hint, Hints, Provenance
from isitright.core.spec import ToolSpec

Status = Literal["proposed", "confirmed", "rejected"]
FORMAT_VERSION = 1


@dataclass(frozen=True)
class ProposalRequest:
    """What a proposer may read: the words of the task and policy, the tools, the entity model."""

    task: str
    policy: str | None
    tools: Sequence[ToolSpec]
    schema: EntitySchema
    existing: Sequence[Hint] = ()
    """Hints the scenario already declares: a proposal may refer to them (``$lookup``)."""


class HintProposer(Protocol):
    """Returns candidate hints for a request. Provenance is set by `propose_hints`, not here."""

    def propose(self, request: ProposalRequest) -> list[Hint]: ...


@dataclass
class ProposalResult:
    hints: list[Hint] = field(default_factory=list)
    rejected: list[tuple[Hint, str]] = field(default_factory=list)
    """Hints the entity model could not resolve, each with the reason."""


class ProposalError(ValueError):
    """A hints file is unreadable or inconsistent."""


def propose_hints(proposer: HintProposer, request: ProposalRequest) -> ProposalResult:
    """Run a proposer. Valid hints come back labeled `proposed`, invalid ones as rejected."""
    result = ProposalResult()
    seen: set[str] = set()
    for hint in proposer.propose(request):
        labeled = hint.model_copy(update={"provenance": Provenance.PROPOSED})
        if labeled.name in seen:
            result.rejected.append((labeled, f"duplicate hint name {labeled.name!r}"))
            continue
        try:
            Hints([*request.existing, labeled]).validate(request.schema)
        except ModelError as error:
            result.rejected.append((labeled, str(error)))
            continue
        seen.add(labeled.name)
        result.hints.append(labeled)
    return result


def write_proposals(
    path: Path, result: ProposalResult, *, scenario: str, notes: dict[str, str] | None = None
) -> None:
    """Write proposals for the owner to edit. Every entry starts as ``status: proposed``."""
    notes = notes or {}
    document: dict[str, Any] = {
        "format": "isitright-hints",
        "version": FORMAT_VERSION,
        "scenario": scenario,
        "instructions": (
            "Edit the hints, then set status to confirmed (kept as a declared hint), proposed "
            "(prioritizes the search, grants no validity tier) or rejected (dropped)."
        ),
        "hints": [
            {
                "name": h.name,
                "kind": h.kind,
                "status": "proposed",
                "args": h.args,
                **({"note": notes[h.name]} if h.name in notes else {}),
            }
            for h in result.hints
        ],
        "rejected_by_the_entity_model": [
            {"name": h.name, "kind": h.kind, "args": h.args, "reason": reason}
            for h, reason in result.rejected
        ],
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ProposalError(f"cannot read hints file {path}: {error}") from error
    if not isinstance(data, dict) or data.get("format") != "isitright-hints":
        raise ProposalError(f"{path} is not an isitright hints file")
    if not isinstance(data.get("hints"), list):
        raise ProposalError(f"{path} has no hints list")
    return data


def confirm_proposals(
    path: Path,
    names: Sequence[str] | None = None,
    *,
    schema: EntitySchema | None = None,
    existing: Sequence[Hint] = (),
) -> list[str]:
    """Mark proposed hints ``confirmed`` (every proposed hint when ``names`` is None).

    With a schema, each hint is re-checked against the entity model first, since the owner may
    have edited it. Returns the names confirmed. A name that is not in the file is an error.
    """
    data = _read(path)
    entries = {str(e.get("name")): e for e in data["hints"]}
    unknown = [n for n in (names or []) if n not in entries]
    if unknown:
        raise ProposalError(f"no such hint: {', '.join(unknown)}")
    chosen = [n for n, e in entries.items() if (names is None and e.get("status") == "proposed")]
    chosen = list(names) if names is not None else chosen
    for name in chosen:
        if schema is not None:
            try:
                Hints([*existing, _hint(entries[name], Provenance.DECLARED)]).validate(schema)
            except ModelError as error:
                raise ProposalError(f"hint {name!r} does not resolve: {error}") from error
        entries[name]["status"] = "confirmed"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return chosen


def _hint(entry: dict[str, Any], provenance: Provenance) -> Hint:
    try:
        return Hint(
            kind=str(entry["kind"]),
            name=str(entry.get("name", "")),
            provenance=provenance,
            args=dict(entry.get("args") or {}),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ProposalError(f"hint entry {entry!r} is malformed: {error}") from error


def load_hints(path: Path, schema: EntitySchema, existing: Sequence[Hint] = ()) -> list[Hint]:
    """Hints from a file: confirmed ones as ``declared``, proposed ones as ``proposed``."""
    out: list[Hint] = []
    for entry in _read(path)["hints"]:
        status = entry.get("status", "proposed")
        if status == "rejected":
            continue
        if status not in ("proposed", "confirmed"):
            raise ProposalError(f"hint {entry.get('name')!r} has unknown status {status!r}")
        hint = _hint(entry, Provenance.DECLARED if status == "confirmed" else Provenance.PROPOSED)
        try:
            Hints([*existing, hint]).validate(schema)
        except ModelError as error:
            raise ProposalError(f"hint {hint.name!r} does not resolve: {error}") from error
        out.append(hint)
    return out
