"""Deterministic `okfx_gaps` writes for the gap-agent fleet.

Agents report a finding; this module serializes it. Hand-written YAML broke the
frontmatter whenever a description carried `: `, and fifteen concurrent agents
editing one mapping lost entries. Both are structural, so neither is the agent's
problem to solve: the value is emitted by the YAML dumper and the read-modify-write
runs under an exclusive lock on the concept.
"""

from __future__ import annotations

import fcntl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from archivist.contracts import (
    GAPS_FIELD,
    INDEX_REL,
    TargetContracts,
    load_contracts,
)
from archivist.errors import ContractError

_GAPS_KEY = GAPS_FIELD
_DELIM = "---"
_WIDTH = 88


class RecordGapError(ContractError):
    """The requested `okfx_gaps` write violates the gap-kinds contract."""


@dataclass(frozen=True, slots=True)
class RecordGapResult:
    kind: str
    action: str
    gaps: int


class _Dumper(yaml.SafeDumper):
    """Indent sequences under their key, matching the surrounding frontmatter."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def _split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != _DELIM:
        raise RecordGapError("concept is missing YAML frontmatter")
    for index in range(1, len(lines)):
        if lines[index].rstrip("\n") == _DELIM:
            return lines[1:index], lines[index:]
    raise RecordGapError("concept frontmatter is not closed")


def _block_bounds(frontmatter: list[str]) -> tuple[int, int] | None:
    """Line span of the existing `okfx_gaps` block, or None when absent."""
    start = None
    for index, line in enumerate(frontmatter):
        if line.startswith(f"{_GAPS_KEY}:"):
            start = index
            break
    if start is None:
        return None
    for index in range(start + 1, len(frontmatter)):
        line = frontmatter[index]
        if line[:1].strip() and not line.startswith(" "):
            return start, index
    return start, len(frontmatter)


def _emit_gaps(gaps: list[dict[str, Any]]) -> list[str]:
    if not gaps:
        return [f"{_GAPS_KEY}: []\n"]
    text = yaml.dump(
        {_GAPS_KEY: gaps},
        Dumper=_Dumper,
        sort_keys=False,
        width=_WIDTH,
        allow_unicode=True,
        default_flow_style=False,
    )
    return text.splitlines(keepends=True)


def _load_frontmatter(frontmatter: list[str]) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load("".join(frontmatter))
    except yaml.YAMLError as exc:
        raise RecordGapError(f"concept frontmatter is invalid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RecordGapError("concept frontmatter must be a YAML mapping")
    return loaded


def _current_gaps(loaded: dict[str, Any]) -> list[dict[str, Any]]:
    raw = loaded.get(_GAPS_KEY)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RecordGapError(f"{_GAPS_KEY} must be a YAML list")
    gaps: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("kind"):
            raise RecordGapError(f"{_GAPS_KEY} entries must be mappings with a kind")
        gaps.append(dict(entry))
    return gaps


def _find_contracts(concept: Path) -> TargetContracts:
    for candidate in [concept.parent, *concept.parents]:
        if (candidate / INDEX_REL).is_file():
            contracts = load_contracts(candidate)
            if "gap-kinds" not in contracts.documents:
                raise RecordGapError(f"{INDEX_REL} declares no gap-kinds contract")
            return contracts
    raise RecordGapError(f"{INDEX_REL} not found above the concept")


def _resolve_kind(concept: Path, loaded: dict[str, Any], kind: str) -> dict[str, Any]:
    """The kind's contract entry, if the kind exists, is enabled and applies to this concept."""
    contracts = _find_contracts(concept)
    document = contracts.gap_kinds()
    contract = next((k for k in document["kinds"] if k["id"] == kind), None)
    if contract is None:
        raise RecordGapError(f"kind {kind!r} is not in {contracts.rel('gap-kinds')}")
    if contract.get("enabled") is False:
        raise RecordGapError(f"kind {kind!r} is disabled")
    okf_type = loaded.get("type")
    type_id = contracts.concept_type_id(str(okf_type))
    if type_id is None:
        raise RecordGapError(f"concept type {okf_type!r} is not in {contracts.rel('concept-types')}")
    if type_id not in contract["applies_to"]:
        raise RecordGapError(f"kind {kind!r} does not apply to {type_id!r}")
    return contract


def _resolve_origin(contract: dict[str, Any], kind: str, origin: str | None) -> str:
    fixed = contract.get("fixed_origin")
    if fixed:
        if origin and origin != fixed:
            raise RecordGapError(f"kind {kind!r} fixes origin to {fixed!r}, got {origin!r}")
        return str(fixed)
    allowed = contract.get("origins") or []
    if not origin:
        raise RecordGapError(f"kind {kind!r} requires an origin from {list(allowed)}")
    if origin not in allowed:
        raise RecordGapError(f"kind {kind!r} origin must be one of {list(allowed)}, got {origin!r}")
    return origin


def record_gap(
    concept: Path,
    *,
    kind: str,
    origin: str | None = None,
    description: str | None = None,
    absent: bool = False,
) -> RecordGapResult:
    """Add, replace, or remove this kind's `okfx_gaps` entry under an exclusive lock."""
    if not kind:
        raise RecordGapError("a kind id is required")
    if not absent and not (description or "").strip():
        raise RecordGapError("a description is required unless the gap is absent")
    path = concept.resolve()
    if not path.is_file():
        raise RecordGapError(f"concept not found: {concept}")

    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            text = handle.read()
            frontmatter, rest = _split_frontmatter(text)
            loaded = _load_frontmatter(frontmatter)
            gaps = _current_gaps(loaded)
            index = next((i for i, gap in enumerate(gaps) if gap["kind"] == kind), None)

            if absent:
                if index is None:
                    action = "unchanged"
                else:
                    del gaps[index]
                    action = "removed"
            else:
                contract = _resolve_kind(path, loaded, kind)
                entry = {
                    "kind": kind,
                    "origin": _resolve_origin(contract, kind, origin),
                    "description": " ".join((description or "").split()),
                }
                if index is None:
                    gaps.append(entry)
                    action = "added"
                elif gaps[index] == entry:
                    action = "unchanged"
                else:
                    gaps[index] = entry
                    action = "updated"

            if action != "unchanged":
                block = _emit_gaps(gaps)
                bounds = _block_bounds(frontmatter)
                if bounds is None:
                    frontmatter = frontmatter + block
                else:
                    start, end = bounds
                    frontmatter = frontmatter[:start] + block + frontmatter[end:]
                handle.seek(0)
                handle.truncate()
                handle.write(f"{_DELIM}\n" + "".join(frontmatter) + "".join(rest))
                handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return RecordGapResult(kind=kind, action=action, gaps=len(gaps))
