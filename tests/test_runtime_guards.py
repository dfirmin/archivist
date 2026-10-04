"""The run-loop guards Python keeps on the conductor, and the target scaffold."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from archivist.dispatch_check import check_entry_stage_ran, planned_groups, planner_gave_up
from archivist.engine import load_engine, resolve_run
from archivist.errors import ContractError
from archivist.stream import StreamMonitor
from archivist.targets import Target
from archivist.workspace import ScaffoldState, detect_scaffold_state, scaffold_workspace

ENGINE = load_engine()


def monitor_with(dispatches: list[tuple[str, str]]) -> StreamMonitor:
    """A monitor fed sub-agent spawns and their replies, as Claude Code streams them."""
    m = StreamMonitor(out=io.StringIO(), err=io.StringIO())
    for i, (agent, reply) in enumerate(dispatches):
        use = {"type": "tool_use", "id": f"t{i}", "name": "Agent", "input": {"subagent_type": agent}}
        m.feed(json.dumps({"type": "assistant", "message": {"content": [use]}}))
        result = {"type": "tool_result", "tool_use_id": f"t{i}", "content": reply}
        m.feed(json.dumps({"type": "user", "message": {"content": [result]}}))
    return m


def test_entry_stage_must_dispatch(warehouse: Path) -> None:
    roster = resolve_run(warehouse, engine=ENGINE).roster
    planned = monitor_with([("intake-planner", "Groups: 1\nGroup 1: custcase — customer-care\n- a.md")])
    assert "without spawning 'author'" in check_entry_stage_ran(planned, ENGINE.profile, roster, inbox_documents=3)
    ran = monitor_with([("intake-planner", "Groups: 1\nGroup 1: x"), ("author", "Authored: 1")])
    assert check_entry_stage_ran(ran, ENGINE.profile, roster, inbox_documents=3) is None


def test_empty_queue_is_a_clean_exit(warehouse: Path) -> None:
    roster = resolve_run(warehouse, engine=ENGINE).roster
    empty = monitor_with([("intake-planner", "Groups: 0\nSkipped:\n- a.md — no row")])
    assert check_entry_stage_ran(empty, ENGINE.profile, roster, inbox_documents=1) is None
    assert not planner_gave_up(empty, "intake-planner")


def test_bare_zero_groups_is_malformed_and_listed_groups_win() -> None:
    assert planner_gave_up(monitor_with([("intake-planner", "Groups: 0")]), "intake-planner")
    miscounted = monitor_with([("intake-planner", "Groups: 0\nGroup 1: a\nGroup 2: b")])
    assert planned_groups(miscounted, "intake-planner") == 2


def test_scaffold_writes_the_minimum_and_validation_names_what_is_missing(tmp_path: Path) -> None:
    target = Target("acme", "Acme Docs", "d", "https://github.com/example-org/acme", "docs", "active", "v0.1.0", False)
    result = scaffold_workspace(tmp_path / "acme", target)
    assert "contracts/target.yaml" in result.written
    workspace = tmp_path / "acme"
    assert detect_scaffold_state(workspace, target) is ScaffoldState.SCAFFOLDED
    assert "slug: acme" in (workspace / "contracts/target.yaml").read_text(encoding="utf-8")
    with pytest.raises(ContractError, match=r"concept-types \(needed by author"):
        resolve_run(workspace, engine=ENGINE)


def test_scaffold_refuses_a_foreign_repo(tmp_path: Path) -> None:
    target = Target("acme", "Acme", "d", "https://github.com/example-org/acme", "docs", "active", "v0.1.0", False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print()\n", encoding="utf-8")
    assert detect_scaffold_state(tmp_path, target) is ScaffoldState.REFUSE
