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
    target = Target("acme", "Acme Docs", "d", "https://github.com/example-org/acme", "docs", "active", False)
    result = scaffold_workspace(tmp_path / "acme", target, engine="v0.1.0")
    assert "contracts/target.yaml" in result.written
    workspace = tmp_path / "acme"
    assert detect_scaffold_state(workspace, target) is ScaffoldState.SCAFFOLDED
    assert "slug: acme" in (workspace / "contracts/target.yaml").read_text(encoding="utf-8")
    with pytest.raises(ContractError, match=r"concept-types \(needed by author"):
        resolve_run(workspace, engine=ENGINE)


def test_scaffold_refuses_a_foreign_repo(tmp_path: Path) -> None:
    target = Target("acme", "Acme", "d", "https://github.com/example-org/acme", "docs", "active", False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print()\n", encoding="utf-8")
    assert detect_scaffold_state(tmp_path, target) is ScaffoldState.REFUSE


class FakeRunner:
    """Records commands; answers like an empty, existing GitHub repo."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args, *, cwd=None):  # type: ignore[no-untyped-def]
        import subprocess

        self.calls.append(list(args))
        if args[:2] == ["git", "clone"]:
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        failing = (args[:3] == ["git", "rev-parse", "--verify"]) or (args[:3] == ["git", "ls-remote", "--exit-code"])
        out = "https://github.com/o/r/pull/1\n" if args[:2] == ["gh", "api"] and "POST" in args else ""
        return subprocess.CompletedProcess(args, 1 if failing else 0, out, "")


def test_prepare_target_uses_git_and_rest_only(tmp_path: Path) -> None:
    from archivist.workspace import prepare_target

    registry = tmp_path / "targets.yaml"
    registry.write_text(
        "targets:\n  - {slug: kb, name: KB, description: d, target_repo: 'https://github.com/o/r',"
        " type: docs, status: active}\n",
        encoding="utf-8",
    )
    runner = FakeRunner()
    result = prepare_target(target_slug="kb", workspace=tmp_path / "kb", registry_path=registry,
                            runner=runner, environ={"ARCHIVIST_PUBLISHER": "1"}, engine="v0.1.0")
    assert result.action == "published" and result.pull_request_url == "https://github.com/o/r/pull/1"
    gh = [c for c in runner.calls if c[0] == "gh"]
    assert all(c[1] == "api" for c in gh), gh  # no GraphQL-backed gh subcommands
    assert ["git", "clone", "https://github.com/o/r.git", str(tmp_path / "kb")] in runner.calls
    assert any(c[:3] == ["gh", "api", "repos/o/r/pulls"] for c in gh)
