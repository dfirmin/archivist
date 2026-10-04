"""Persist redacted transcripts of a conductor session and each sub-agent it spawned.

Claude Code's ``--output-format stream-json`` emits every message of the run, and marks
messages that belong to a sub-agent with ``parent_tool_use_id`` (the id of the ``Task``
call that spawned it). ``TranscriptRecorder`` groups events by that id and writes one JSON
file per dispatched sub-agent plus one for the conductor itself, so a bounded categorized
run keeps evidence after its process exits and releases its memory.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
ENV_TRANSCRIPT_DIR = "CHILD_SESSION_TRANSCRIPT_DIR"
DEFAULT_TRANSCRIPT_ROOT = Path("/out/transcripts")
CONDUCTOR_KEY = "conductor"

_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|authorization|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|cookie|bearer|gh[_-]?token|github[_-]?token|auth)",
    re.IGNORECASE,
)
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bghp_[A-Za-z0-9]+\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\bx-api-key:\s*\S+"),
)
_REDACTED = "***REDACTED***"


def transcript_root() -> Path:
    raw = os.environ.get(ENV_TRANSCRIPT_DIR, "").strip()
    return Path(raw) if raw else DEFAULT_TRANSCRIPT_ROOT


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _VALUE_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def redact_secrets(value: Any) -> Any:
    """Recursively redact obvious secret/token/auth material."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY.search(key):
                out[key] = _REDACTED
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _inbox_paths(workspace: Path, inbox_files: tuple[str, ...]) -> tuple[str, ...]:
    paths: list[str] = list(inbox_files)
    rel = os.environ.get("INBOX_FILE", "").strip()
    if rel:
        paths.append(rel)
    manifest = os.environ.get("CONDUCTOR_INBOX_MANIFEST", "").strip()
    if manifest:
        manifest_path = Path(manifest)
        if not manifest_path.is_absolute():
            manifest_path = workspace / manifest_path
        if manifest_path.is_file():
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped:
                    paths.append(stripped)
    return tuple(dict.fromkeys(paths))


def end_artifact_state(
    workspace: Path, inbox_files: tuple[str, ...] = (), *, since: float | None = None
) -> dict[str, Any]:
    """Concepts written during the session and where each named inbox document ended up."""
    root = workspace / "knowledge"
    concept_paths = sorted(
        str(path.relative_to(workspace))
        for path in root.rglob("*.md")
        if path.is_file() and (since is None or path.stat().st_mtime >= since)
    ) if root.is_dir() else []
    inbox_rows: list[dict[str, Any]] = []
    for rel in _inbox_paths(workspace, inbox_files):
        processed = rel.replace("sources/inbox/", "sources/processed/", 1)
        moved = (workspace / processed).is_file()
        inbox_rows.append(
            {
                "path": rel,
                "still_in_inbox": (workspace / rel).is_file(),
                "processed_path": processed if moved else None,
                "moved_to_processed": moved,
            }
        )
    return {"concepts_written": concept_paths, "inbox": inbox_rows}


def _slug_fragment(value: str, *, limit: int = 48) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not cleaned:
        return "unknown"
    return cleaned[:limit]


def transcript_filename(
    *,
    group_key: str,
    agent_name: str,
    dispatch_title: str | None,
    session_id: str,
) -> str:
    title_part = _slug_fragment(dispatch_title or "session")
    return (
        f"{_slug_fragment(group_key)}__{_slug_fragment(agent_name)}__"
        f"{title_part}__{_slug_fragment(session_id)}.json"
    )


def _group_key(session_id: str) -> str:
    return (
        os.environ.get("CONDUCTOR_GROUP_RUN_BRANCH", "").strip()
        or os.environ.get("CONDUCTOR_GROUP_LABEL", "").strip()
        or session_id
    )


def _parent_metadata(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_name": CONDUCTOR_KEY,
        "group_label": os.environ.get("CONDUCTOR_GROUP_LABEL", "").strip() or None,
        "run_branch": os.environ.get("RUN_BRANCH", "").strip() or None,
        "group_run_branch": os.environ.get("CONDUCTOR_GROUP_RUN_BRANCH", "").strip() or None,
    }


class TranscriptRecorder:
    """Collect redacted stream events, keyed by the ``Task`` call that spawned them."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {CONDUCTOR_KEY: []}
        self._children: dict[str, dict[str, Any]] = {}
        self._started = time.time()

    def add_event(self, event: dict[str, Any]) -> None:
        parent = event.get("parent_tool_use_id")
        key = parent if isinstance(parent, str) and parent else CONDUCTOR_KEY
        self._events.setdefault(key, []).append(redact_secrets(event))

    def add_dispatch(
        self,
        tool_use_id: str,
        *,
        agent: str,
        description: str | None,
        prompt: str | None,
    ) -> None:
        self._children[tool_use_id] = {
            "agent_name": agent,
            "description": description,
            "prompt": redact_secrets(prompt),
        }

    def write(
        self,
        *,
        session_id: str,
        workspace: Path,
        inbox_files: tuple[str, ...] = (),
        results: dict[str, str] | None = None,
    ) -> list[Path]:
        """Write one file per child and one for the conductor; return the paths."""
        root = transcript_root()
        root.mkdir(parents=True, exist_ok=True)
        group_key = _group_key(session_id)
        artifacts = end_artifact_state(workspace, inbox_files, since=self._started)
        captured_at = datetime.now(UTC).isoformat()
        written: list[Path] = []

        def emit(agent: str, title: str | None, unit_id: str, record: dict[str, Any]) -> None:
            path = root / transcript_filename(
                group_key=group_key,
                agent_name=agent,
                dispatch_title=title,
                session_id=unit_id,
            )
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            written.append(path)

        for tool_use_id, meta in self._children.items():
            events = self._events.get(tool_use_id, [])
            emit(
                meta["agent_name"],
                meta["description"],
                tool_use_id,
                {
                    "schema_version": SCHEMA_VERSION,
                    "captured_at": captured_at,
                    "parent": _parent_metadata(session_id),
                    "child": {
                        "tool_use_id": tool_use_id,
                        **meta,
                        "result": redact_secrets((results or {}).get(tool_use_id)),
                    },
                    "events": events,
                    "artifacts": artifacts,
                },
            )
        emit(
            CONDUCTOR_KEY,
            None,
            session_id,
            {
                "schema_version": SCHEMA_VERSION,
                "captured_at": captured_at,
                "parent": _parent_metadata(session_id),
                "child": None,
                "events": self._events[CONDUCTOR_KEY],
                "artifacts": artifacts,
            },
        )
        return written
