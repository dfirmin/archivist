"""ADR 0009: contracts preloaded into agent prompts, and inbox scans with groups in parallel.

The scheduler is tested against scripted sessions: what it starts, in what order, with which
kickoff, and what it holds. Agents' work is not simulated beyond moving inbox files."""

from __future__ import annotations

import io
import shutil
import threading
import time
from pathlib import Path

import pytest

from archivist.claude_runner import prepare_agent_workspace
from archivist.dispatch_check import parse_plan
from archivist.engine import resolve_run
from archivist.harness import ClaudeCodeHarness
from archivist.parallel import ParallelRun
from archivist.preload import FILE_CAP, contract_section

# ------------------------------------------------------------------------- preload


def _agent_file(workspace: Path, name: str) -> str:
    return (workspace / ".claude" / "agents" / f"{name}.md").read_text()


def test_each_agent_gets_the_contracts_its_profile_names(warehouse: Path) -> None:
    prepare_agent_workspace(warehouse)
    gap = _agent_file(warehouse, "gap-agent")
    assert "# Target contracts for this run (already read)" in gap
    for rel in ("contracts/target.yaml", "contracts/gap-kinds.yaml", "contracts/reference/source-systems.yaml"):
        assert f"## `{rel}`" in gap
    assert "contracts/scoring.yaml" not in gap  # not the gap-agent's
    assert (warehouse / "contracts/gap-kinds.yaml").read_text().strip()[:200] in gap  # verbatim
    assert "# Target contracts" not in _agent_file(warehouse, "verifier")  # uses no contracts


def test_preload_can_be_turned_off(warehouse: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ARCHIVIST_PRELOAD_CONTRACTS", "0")
    prepare_agent_workspace(warehouse)
    assert "# Target contracts" not in _agent_file(warehouse, "gap-agent")


def test_large_reference_data_stays_on_disk(warehouse: Path) -> None:
    big = warehouse / "contracts" / "reference" / "inventory.csv"
    big.write_text(big.read_text() + ("x," * (FILE_CAP // 2)) + "\n")
    run = resolve_run(warehouse)
    section = contract_section("gap-agent", run.engine.profile, run.contracts)
    assert "## `contracts/reference/inventory.csv`" not in section
    assert "- `contracts/reference/inventory.csv`" in section.split("## Not loaded")[1]


# -------------------------------------------------------------------- plan parsing


def test_parse_plan_reads_every_group_in_order() -> None:
    text = (
        "Groups: 3\nGroup 1: extract — transcripts\n- sources/inbox/a.md\n"
        "Group 2: out-of-scope — no row\n- `sources/inbox/b.md`\n"
        "Group 3: claim-header — CLAIM_HDR_SV\n- sources/inbox/c.md\n- sources/inbox/d.md\n"
    )
    groups = parse_plan(text)
    assert [g.slug for g in groups] == ["extract", "out-of-scope", "claim-header"]
    assert groups[2].documents == ("sources/inbox/c.md", "sources/inbox/d.md")
    assert parse_plan("Groups: 0") == []


# ------------------------------------------------------------------------ scheduler


class Script:
    """Scripted sessions: plans by round, and groups that move (or keep) their documents."""

    def __init__(self, workspace: Path, plans: list[str], keep: set[str] = frozenset()) -> None:
        self.workspace, self.plans, self.keep = workspace, plans, set(keep)
        self.calls: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def launch(self, argv, *, env, cwd, prompt, monitor) -> int:  # type: ignore[no-untyped-def]
        agent = argv[argv.index("--agent") + 1]
        if agent == "intake-planner":
            monitor.final_text = self.plans.pop(0)
            self.calls.append(("plan", prompt))
            monitor.saw_result = True
            return 0
        kind = "finish" if "Work: finishing" in prompt else "extract" if "group `extract`" in prompt else "group"
        with self.lock:
            self.calls.append((kind, prompt))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if kind == "group":
                time.sleep(0.2)
                monitor.dispatches["t1"] = __import__("archivist.stream", fromlist=["Dispatch"]).Dispatch("t1", "author", "x")
            for line in prompt.splitlines():
                doc = line.strip("- `")
                if kind in ("group", "extract") and doc.startswith("sources/inbox/") and doc not in self.keep:
                    src = self.workspace / doc
                    if src.exists():
                        dest = self.workspace / "sources" / "processed" / src.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        src.rename(dest)
                        if kind == "extract":
                            (self.workspace / "sources/inbox" / f"{src.stem}--topic.md").write_text("x")
            monitor.final_text = f"== Archivist run complete ==\nConcepts: knowledge/{kind}.md"
            return 0
        finally:
            with self.lock:
                self.active -= 1


def _inbox(workspace: Path, *names: str) -> None:
    inbox = workspace / "sources" / "inbox"
    shutil.rmtree(inbox, ignore_errors=True)
    inbox.mkdir(parents=True)
    for name in names:
        (inbox / name).write_text("x")


def _run(workspace: Path, script: Script, *, publish: bool = False, parallel: int = 3) -> ParallelRun:
    run = resolve_run(workspace)
    pr = ParallelRun(
        workspace=workspace, harness=ClaudeCodeHarness(), env={}, model=None, planner_model=None,
        agents=(), profile=run.engine.profile, roster=run.roster, branch="archivist/run-x",
        skip_publish=not publish, parallel=parallel, launch=script.launch,
    )
    prepare_agent_workspace(workspace)
    return pr


def _plan(*groups: tuple[str, tuple[str, ...]]) -> str:
    lines = [f"Groups: {len(groups)}"]
    for i, (slug, docs) in enumerate(groups, 1):
        lines.append(f"Group {i}: {slug} — label")
        lines.extend(f"- sources/inbox/{d}" for d in docs)
    return "\n".join(lines)


def test_groups_run_in_parallel_then_finish_in_plan_order(handbook: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _inbox(handbook, "a.md", "b.md", "c.md")
    script = Script(handbook, [_plan(("alpha", ("a.md",)), ("beta", ("b.md",)), ("gamma", ("c.md",)))])
    assert _run(handbook, script).run() == 0
    kinds = [k for k, _ in script.calls]
    assert kinds == ["plan", "group", "group", "group", "finish"] or sorted(kinds[1:4]) == ["group"] * 3
    assert script.max_active == 3
    finish = script.calls[-1][1]
    assert finish.index("`alpha`") < finish.index("`beta`") < finish.index("`gamma`")
    assert all("Catalog and publish: later" in p for k, p in script.calls if k == "group")


def test_extraction_runs_alone_first_and_the_inbox_is_planned_again(handbook: Path) -> None:
    _inbox(handbook, "call.md", "a.md")
    script = Script(handbook, [
        _plan(("extract", ("call.md",)), ("alpha", ("a.md",))),
        _plan(("alpha", ("a.md", "call--topic.md"))),
    ])
    assert _run(handbook, script).run() == 0
    assert [k for k, _ in script.calls] == ["plan", "extract", "plan", "group", "finish"]


def test_a_document_left_twice_is_held(handbook: Path) -> None:
    _inbox(handbook, "a.md", "amend.md")
    script = Script(handbook, [
        _plan(("alpha", ("a.md",)), ("amendment", ("amend.md",))),
        _plan(("amendment", ("amend.md",))),
    ], keep={"sources/inbox/amend.md"})
    assert _run(handbook, script).run() == 0
    assert [k for k, _ in script.calls] == ["plan", "group", "group", "finish", "plan", "group", "finish"]
    assert (handbook / "sources/inbox/amend.md").exists()  # held, not looped on


def test_publishing_creates_the_branch_once(handbook: Path) -> None:
    _inbox(handbook, "call.md", "a.md")
    script = Script(handbook, [_plan(("extract", ("call.md",))), _plan(("alpha", ("a.md", "call--topic.md")))])
    assert _run(handbook, script, publish=True).run() == 0
    extract = next(p for k, p in script.calls if k == "extract")
    finish = next(p for k, p in script.calls if k == "finish")
    assert "Publish: yes, on branch `archivist/run-x`." in extract
    assert "already created and pushed" in finish
    assert all("Publish:" not in p for k, p in script.calls if k == "group")  # groups leave git alone
