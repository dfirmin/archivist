"""The scope of a run over published concepts, and the write fence that holds it (ADR 0004).

A run that skips authoring works on existing concepts: one, several, or ``all`` of them, and
optionally only some gap kinds. Python resolves that selection from the contracts (which
files are concepts, which kinds exist and apply), because each answer is a lookup with one
right result. The judging stays with the agents.

When every stage of a run declares ``writes`` in the profile, the run is fenced: a snapshot
of ``knowledge/`` before a session is compared with the tree after it, and any change beyond
those frontmatter fields on the session's own concepts fails the run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archivist.contracts import TargetContracts
from archivist.errors import ArchivistError, DefinitionError
from archivist.frontmatter import split_frontmatter
from archivist.workspace import KNOWLEDGE_DIR

ALL = "all"
GAP_STAGE = "gap-agent"


class ScopeError(ArchivistError):
    """The requested concepts or kinds cannot be resolved against the target."""


@dataclass(frozen=True, slots=True)
class Selection:
    concepts: tuple[str, ...]
    kinds: tuple[str, ...] | None
    skipped: tuple[tuple[str, str], ...] = ()


def bundle_file(workspace: Path, rel: str, *, label: str) -> str:
    """A bundle-relative path to an existing file inside ``workspace``."""
    if not rel.strip() or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ScopeError(f"{label} must be a bundle-relative path without '..': {rel!r}")
    path = (workspace / rel).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ScopeError(f"{label} must resolve inside the workspace: {rel!r}")
    if not path.is_file():
        raise ScopeError(f"{label} not found: {rel}")
    return Path(rel).as_posix()


def _concept_type(path: Path) -> Any:
    try:
        data, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except (DefinitionError, OSError, UnicodeDecodeError):
        return None
    return data.get("type")


def published_concepts(workspace: Path, contracts: TargetContracts) -> list[tuple[str, str]]:
    """(bundle-relative path, concept-type id) for every authored concept under ``knowledge/``.

    Only ``authored: true`` types count: companions (stubs a concept type creates beside the
    authored one) never pass through the gap fleet or the scorer in a full run either. A live
    ``--concept all`` run picked them up and would have scored stubs.
    """
    types = contracts.concept_types()
    root = workspace / KNOWLEDGE_DIR
    found = []
    for path in sorted(root.rglob("*.md")) if root.is_dir() else ():
        okf_type = _concept_type(path)
        type_id = contracts.concept_type_id(str(okf_type)) if okf_type else None
        if type_id is not None and types[type_id].get("authored"):
            found.append((path.relative_to(workspace).as_posix(), type_id))
    return found


def _check_kinds(contracts: TargetContracts, kinds: Sequence[str]) -> dict[str, dict[str, Any]]:
    if "gap-kinds" not in contracts.documents:
        raise ScopeError("--kind needs a gap-kinds contract; the target declares none")
    defined = {k["id"]: k for k in contracts.gap_kinds()["kinds"]}
    chosen: dict[str, dict[str, Any]] = {}
    for kind in kinds:
        spec = defined.get(kind)
        if spec is None:
            raise ScopeError(f"kind {kind!r} is not in {contracts.rel('gap-kinds')} ({', '.join(sorted(defined))})")
        if spec.get("enabled") is False:
            raise ScopeError(f"kind {kind!r} is disabled in {contracts.rel('gap-kinds')}")
        chosen[kind] = spec
    return chosen


def select(
    workspace: Path,
    contracts: TargetContracts,
    *,
    concepts: Sequence[str],
    kinds: Sequence[str] = (),
    stages: Sequence[str],
) -> Selection:
    """Resolve ``--concept`` (paths or ``all``) and ``--kind`` for a run on existing concepts."""
    kinds = tuple(dict.fromkeys(k.strip() for k in kinds if k.strip()))
    if kinds and GAP_STAGE not in stages:
        raise ScopeError(f"--kind needs a pipeline with {GAP_STAGE!r}; this one runs {', '.join(stages)}")
    chosen_kinds = _check_kinds(contracts, kinds) if kinds else {}

    requested = [c.strip() for c in concepts if c.strip()]
    if ALL in requested:
        if len(requested) > 1:
            raise ScopeError("--concept all does not combine with concept paths")
        candidates = published_concepts(workspace, contracts)
    else:
        candidates = []
        for rel in dict.fromkeys(requested):
            rel = bundle_file(workspace, rel, label="concept file")
            okf_type = _concept_type(workspace / rel)
            type_id = contracts.concept_type_id(str(okf_type)) if okf_type else None
            if type_id is None:
                raise ScopeError(f"{rel}: `type: {okf_type}` is not a concept type in the contracts")
            candidates.append((rel, type_id))

    selected: list[str] = []
    skipped: list[tuple[str, str]] = []
    for rel, type_id in candidates:
        if chosen_kinds and not any(type_id in spec["applies_to"] for spec in chosen_kinds.values()):
            skipped.append((rel, f"no kind in scope applies to {type_id}"))
            continue
        selected.append(rel)
    return Selection(tuple(selected), kinds or None, tuple(skipped))


def batches(items: Sequence[str], size: int) -> list[tuple[str, ...]]:
    if size < 1:
        raise ScopeError("--concept-batch must be at least 1")
    return [tuple(items[i : i + size]) for i in range(0, len(items), size)]


# --------------------------------------------------------------------------- write fence


@dataclass(frozen=True, slots=True)
class _Entry:
    text: str
    frontmatter: dict[str, Any] | None
    body: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    files: dict[str, _Entry] = field(default_factory=dict)


def snapshot(workspace: Path) -> Snapshot:
    """Every Markdown file under ``knowledge/``, parsed where its frontmatter parses."""
    root = workspace / KNOWLEDGE_DIR
    files: dict[str, _Entry] = {}
    for path in sorted(root.rglob("*.md")) if root.is_dir() else ():
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            data, body = split_frontmatter(text)
            entry = _Entry(text, data if text.startswith("---\n") else None, body)
        except DefinitionError:
            entry = _Entry(text, None, text)
        files[path.relative_to(workspace).as_posix()] = entry
    return Snapshot(files)


def fence_violations(
    before: Snapshot,
    after: Snapshot,
    *,
    scope: Iterable[str],
    fields: Iterable[str],
) -> list[str]:
    """What changed beyond ``fields`` on the ``scope`` concepts; empty when the fence held."""
    scope, fields = set(scope), set(fields)
    problems: list[str] = []
    for rel in sorted(set(before.files) | set(after.files)):
        old, new = before.files.get(rel), after.files.get(rel)
        if old is None:
            problems.append(f"{rel}: created")
            continue
        if new is None:
            problems.append(f"{rel}: deleted")
            continue
        if old.text == new.text:
            continue
        if rel not in scope:
            problems.append(f"{rel}: changed, but it is not in this session's scope")
            continue
        if old.frontmatter is None or new.frontmatter is None:
            problems.append(f"{rel}: frontmatter no longer parses")
            continue
        if old.body != new.body:
            problems.append(f"{rel}: body changed")
        changed = sorted(
            key
            for key in set(old.frontmatter) | set(new.frontmatter)
            if key not in fields and old.frontmatter.get(key) != new.frontmatter.get(key)
        )
        if changed:
            problems.append(f"{rel}: frontmatter field(s) outside {sorted(fields)} changed: {', '.join(changed)}")
    return problems

