"""``archivist requeue``: send a quarantined draft's documents back to the inbox (ADR 0005).

The author quarantines what it cannot place: the draft goes to ``quarantine/`` and its source
documents to ``sources/quarantine/``. An owner resolves the stated need, usually by a contract
change, and then requeues: the documents move back to ``sources/inbox/`` and the draft is
deleted, so the next run authors them with the fixed contracts and every later stage runs.
Two moves and a delete hold no judgement, so a command does them rather than an agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from archivist.check_concept import QUARANTINE_DIR, QUARANTINED
from archivist.contracts import INDEX_REL
from archivist.errors import ArchivistError, DefinitionError
from archivist.frontmatter import split_frontmatter
from archivist.workspace import INBOX_DIR

SOURCES_QUARANTINE_DIR = "sources/quarantine"


class RequeueError(ArchivistError):
    """The file is not a quarantined draft whose documents can go back to the inbox."""


@dataclass(frozen=True, slots=True)
class RequeueResult:
    draft: str
    moved: tuple[tuple[str, str], ...]


def _bundle_root(path: Path) -> Path:
    for candidate in path.parents:
        if (candidate / INDEX_REL).is_file():
            return candidate
    raise RequeueError(f"{INDEX_REL} not found above {path}")


def requeue(draft: Path) -> RequeueResult:
    """Move every document the draft cites from sources/quarantine/ to the inbox; delete it."""
    draft = draft.resolve()
    if not draft.is_file():
        raise RequeueError(f"not found: {draft}")
    root = _bundle_root(draft)
    rel = draft.relative_to(root)
    if rel.parts[0] != QUARANTINE_DIR or rel.name == "README.md":
        raise RequeueError(f"{rel.as_posix()} is not a quarantined draft under {QUARANTINE_DIR}/")
    try:
        data, _ = split_frontmatter(draft.read_text(encoding="utf-8"))
    except DefinitionError as err:
        raise RequeueError(f"{rel.as_posix()}: {err}") from err
    if data.get("status") != QUARANTINED:
        raise RequeueError(f"{rel.as_posix()} does not have `status: {QUARANTINED}`")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RequeueError(f"{rel.as_posix()} lists no `sources`; nothing to send back to the inbox")
    moves: list[tuple[Path, Path]] = []
    for i, entry in enumerate(sources):
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not resource:
            raise RequeueError(f"{rel.as_posix()}: `sources[{i}]` has no `resource`")
        resource_path = PurePosixPath(str(resource))
        if resource_path.parent.as_posix() != SOURCES_QUARANTINE_DIR:
            raise RequeueError(
                f"{rel.as_posix()}: `sources[{i}]` is {resource}, not a document in {SOURCES_QUARANTINE_DIR}/"
            )
        source = root / resource_path
        target = root / INBOX_DIR / resource_path.name
        if not source.is_file():
            raise RequeueError(f"{rel.as_posix()}: {resource} does not exist")
        if target.exists():
            raise RequeueError(f"{INBOX_DIR}/{resource_path.name} already exists; resolve the clash first")
        moves.append((source, target))

    (root / INBOX_DIR).mkdir(parents=True, exist_ok=True)
    for source, target in moves:
        source.rename(target)
    draft.unlink()
    return RequeueResult(
        rel.as_posix(),
        tuple((s.relative_to(root).as_posix(), t.relative_to(root).as_posix()) for s, t in moves),
    )
