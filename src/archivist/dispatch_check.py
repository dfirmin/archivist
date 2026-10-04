"""The one check Python keeps on the conductor: did the run's entry stage ever start?

Live runs showed the conductor can plan an inbox scan, write a report and end with
``result ok`` without spawning the author. A session that produced no work must not report
PASS, so this compares the stream against the roster. It asks for the entry stage only:
later stages may be skipped legitimately when an earlier one fails for a concept.

The planner's reply is parsed for its group count because two live failures (a bare
``Groups: 0`` over a non-empty inbox, and a count that disagreed with its own list) are
structural, not judgement.
"""

from __future__ import annotations

import re

from archivist.profile import Profile, Roster, entry_stage
from archivist.stream import StreamMonitor

_GROUPS = re.compile(r"^\s*Groups:\s*(\d+)", re.MULTILINE)
_GROUP_LINE = re.compile(r"^\s*Group\s+\d+\s*:", re.MULTILINE)


def _planner_reply(monitor: StreamMonitor, planner: str) -> str | None:
    for dispatch in monitor.dispatches.values():
        if dispatch.agent == planner:
            return monitor.results.get(dispatch.tool_use_id, "")
    return None


def planned_groups(monitor: StreamMonitor, planner: str) -> int | None:
    """The planner's group count (the larger of stated and listed), or None if it never said."""
    text = _planner_reply(monitor, planner)
    if text is None:
        return None
    match = _GROUPS.search(text)
    if not match:
        return None
    return max(int(match.group(1)), len(_GROUP_LINE.findall(text)))


def planner_gave_up(monitor: StreamMonitor, planner: str) -> bool:
    """A bare ``Groups: 0`` with no ``Skipped:`` list is malformed, not an empty queue."""
    if planned_groups(monitor, planner) != 0:
        return False
    return "Skipped:" not in (_planner_reply(monitor, planner) or "")


def check_entry_stage_ran(
    monitor: StreamMonitor,
    profile: Profile,
    roster: Roster,
    *,
    inbox_documents: int | None,
) -> str | None:
    """A failure message when the session never started the entry stage, else None.

    ``inbox_documents`` is the inbox size at launch for an inbox scan, None when the run
    names a document or a concept (those always have work).
    """
    stage = entry_stage(profile, roster)
    if stage in monitor.dispatched_agents:
        return None
    if inbox_documents == 0 or planned_groups(monitor, profile.planner) == 0:
        return None
    return (
        f"the conductor ended the session without spawning {stage!r}, the entry stage of "
        f"pipeline {roster.pipeline!r}; nothing was produced"
    )
