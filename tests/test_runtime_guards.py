"""The run-loop guards Python keeps on the conductor, and the target scaffold."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from archivist.dispatch_check import check_entry_stage_ran, first_group_documents, planned_groups, planner_gave_up
from archivist.engine import load_engine, resolve_run
from archivist.engines import EngineVersionError
from archivist.errors import ContractError, WorkspaceError
from archivist.stream import StreamMonitor
from archivist.targets import Target
from archivist.workspace import ScaffoldState, detect_scaffold_state, scaffold_workspace
from conftest import edit_yaml

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


def test_an_extraction_session_counts_as_work(handbook: Path) -> None:
    edit_yaml(handbook / "contracts/intake.yaml", lambda d: d["classes"].append(
        {"id": "call", "description": "A call transcript.", "mode": "extract", "extract": "Keep policies."}))
    roster = resolve_run(handbook, engine=ENGINE, pipeline="author-verify").roster
    extracted = monitor_with([("intake-planner", "Groups: 1\nGroup 1: extract — a call\n- a.md"),
                              ("extractor", "Extracted: 2 from a.md")])
    assert check_entry_stage_ran(extracted, ENGINE.profile, roster, inbox_documents=1) is None
    planned_only = monitor_with([("intake-planner", "Groups: 1\nGroup 1: extract — a call\n- a.md")])
    assert "without spawning 'author'" in check_entry_stage_ran(planned_only, ENGINE.profile, roster, inbox_documents=1)


def test_empty_queue_is_a_clean_exit(warehouse: Path) -> None:
    roster = resolve_run(warehouse, engine=ENGINE).roster
    empty = monitor_with([("intake-planner", "Groups: 0")])
    assert check_entry_stage_ran(empty, ENGINE.profile, roster, inbox_documents=0) is None


def test_zero_groups_over_documents_is_malformed_and_listed_groups_win() -> None:
    # Out-of-scope documents form a group of their own (ADR 0005), so a non-empty inbox
    # always plans at least one group; the runner asks only when the inbox held documents.
    assert planner_gave_up(monitor_with([("intake-planner", "Groups: 0")]), "intake-planner")
    skipped = monitor_with([("intake-planner", "Groups: 0\nSkipped:\n- a.md — no row")])
    assert planner_gave_up(skipped, "intake-planner")
    planned = monitor_with([("intake-planner", "Groups: 1\nGroup 1: out-of-scope — quarantine\n- a.md")])
    assert not planner_gave_up(planned, "intake-planner")
    miscounted = monitor_with([("intake-planner", "Groups: 0\nGroup 1: a\nGroup 2: b")])
    assert planned_groups(miscounted, "intake-planner") == 2


TARGET = Target("acme", "Acme Docs", "d", "https://github.com/example-org/acme", "docs", "active", False)


def test_fresh_scaffold_is_a_runnable_target_with_examples(tmp_path: Path) -> None:
    workspace = tmp_path / "acme"
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    assert detect_scaffold_state(workspace, TARGET) is ScaffoldState.SCAFFOLDED
    assert {"contracts/target.yaml", "contracts/structures/article.yaml", "examples/README.md"} <= set(result.written)
    assert (workspace / "examples/warehouse/contracts/target.yaml").is_file()
    assert (workspace / "examples/minimal/contracts/structures/policy-summary.yaml").is_file()
    run = resolve_run(workspace, engine=ENGINE, pipeline="full")  # every requirement is declared
    assert run.roster.stages == ("author", "enricher", "verifier", "gap-agent", "scorer")
    assert scaffold_workspace(workspace, TARGET, engine="v0.1.0").written == ()  # idempotent


def test_scaffold_completes_an_index_that_declares_nothing(tmp_path: Path) -> None:
    """A pre-starter scaffold (empty contracts, no pin) is upgraded in place."""
    workspace = tmp_path / "acme"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    (workspace / "contracts/target.yaml").write_text("version: 1\nslug: acme\ncontracts: {}\n", encoding="utf-8")
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    assert "contracts/target.yaml" in result.written
    resolve_run(workspace, engine=ENGINE, pipeline="full")


def test_scaffold_only_pins_an_index_the_target_has_written(tmp_path: Path) -> None:
    workspace = tmp_path / "acme"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    own = "version: 1\nslug: acme\ncontracts:\n  concept-types: concept-types.yaml\n"
    (workspace / "contracts/target.yaml").write_text(own, encoding="utf-8")
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    assert result.written == ("contracts/target.yaml (engine pin added)",)
    text = (workspace / "contracts/target.yaml").read_text(encoding="utf-8")
    assert text == "version: 1\nslug: acme\nengine: v0.1.0\ncontracts:\n  concept-types: concept-types.yaml\n"


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


def test_scaffold_migrates_the_references_layout(tmp_path: Path) -> None:
    """A target scaffolded with references/ moves to sources/, citations follow, pin moves."""
    workspace = tmp_path / "acme"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    for old in ("references/inbox/documents", "references/processed/documents"):
        (workspace / old).mkdir(parents=True)
        (workspace / old / ".gitkeep").write_text("", encoding="utf-8")
    (workspace / "references/processed/documents/a.md").write_text("source\n", encoding="utf-8")
    (workspace / "references/inbox/documents/b.md").write_text("waiting\n", encoding="utf-8")
    import shutil

    shutil.rmtree(workspace / "sources")
    concept = workspace / "knowledge/articles/A.md"
    concept.parent.mkdir(parents=True)
    concept.write_text("---\nsources:\n  - {resource: references/processed/documents/a.md}\n---\n"
                       "*Source: [a](references/processed/documents/a.md)*\n", encoding="utf-8")
    (workspace / "README.md").write_text("└── references/       # Source documents concepts cite\n", encoding="utf-8")
    (workspace / "index.md").write_text(
        "## References\n\n- Raw inputs: `references/inbox/`\n- Consumed inputs: `references/processed/`\n",
        encoding="utf-8",
    )
    assert detect_scaffold_state(workspace, TARGET) is ScaffoldState.SCAFFOLDED

    result = scaffold_workspace(workspace, TARGET, engine="v0.2.0")
    assert "references" not in (workspace / "README.md").read_text(encoding="utf-8")
    assert (workspace / "index.md").read_text(encoding="utf-8").startswith("## Sources\n")
    assert not (workspace / "references").exists()
    assert (workspace / "sources/processed/a.md").read_text(encoding="utf-8") == "source\n"
    assert (workspace / "sources/inbox/b.md").is_file()
    text = concept.read_text(encoding="utf-8")
    assert "references/" not in text and text.count("sources/processed/a.md") == 2
    assert "engine: v0.2.0" in (workspace / "contracts/target.yaml").read_text(encoding="utf-8")
    assert any("pin set to v0.2.0" in w for w in result.written)


def test_a_partial_repo_without_knowledge_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "acme"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    (workspace / "knowledge/.gitkeep").unlink()
    (workspace / "knowledge").rmdir()
    assert detect_scaffold_state(workspace, TARGET) is ScaffoldState.REFUSE


def test_a_pin_moves_only_through_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from archivist.workspace import upgrade_target

    workspace = tmp_path / "acme"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    with pytest.raises(WorkspaceError, match="--upgrade v0.3.0"):
        scaffold_workspace(workspace, TARGET, engine="v0.3.0")

    registry = tmp_path / "targets.yaml"
    registry.write_text("targets:\n  - {slug: acme, name: Acme Docs, description: d,"
                        " target_repo: 'https://github.com/example-org/acme', type: docs, status: active}\n",
                        encoding="utf-8")
    (workspace / "knowledge/kept.md").write_text("untouched\n", encoding="utf-8")
    (workspace / "quarantine/README.md").unlink()  # a target scaffolded before quarantine existed
    monkeypatch.setattr("archivist.workspace.running_version", lambda: "v1.2.3")  # upgrade to this engine
    result = upgrade_target(target_slug="acme", workspace=workspace, pin="v1.2.3",
                            registry_path=registry, local=True)
    assert (result.previous, result.pin, result.action) == ("v0.1.0", "v1.2.3", "local")
    assert "PASS  contracts valid" in result.validation
    assert "engine: v1.2.3" in (workspace / "contracts/target.yaml").read_text(encoding="utf-8")
    assert (workspace / "knowledge/kept.md").read_text(encoding="utf-8") == "untouched\n"
    assert "quarantine/README.md" in result.written  # the missing layout note is seeded
    with pytest.raises(EngineVersionError, match="development build"):
        upgrade_target(target_slug="acme", workspace=workspace, pin="v1.2.4.dev1", registry_path=registry, local=True)


def test_the_first_group_is_read_from_the_planner_reply() -> None:
    reply = ("Groups: 2\nGroup 1: out-of-scope — amendment awaiting its rule\n- sources/inbox/re-br-hom-022.md\n"
             "Group 2: custcase — Customer Case\n- `sources/inbox/a.md`\n- sources/inbox/b.md")
    assert first_group_documents(monitor_with([("intake-planner", reply)]), "intake-planner") == [
        "sources/inbox/re-br-hom-022.md"]
    assert first_group_documents(monitor_with([("intake-planner", "Groups: 0")]), "intake-planner") == []


MIRROR = Target("mirror", "Mirror KB", "d", "https://github.com/example-org/mirror", "test", "active", False,
                mirrors="warehouse")
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "warehouse"


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_mirrored_target_is_seeded_with_its_example(tmp_path: Path) -> None:
    workspace = tmp_path / "mirror"
    scaffold_workspace(workspace, MIRROR, engine="v0.1.0")
    contracts, example = _tree(workspace / "contracts"), _tree(EXAMPLE / "contracts")
    assert set(contracts) == set(example)  # no starter contracts left over
    assert {k: v for k, v in contracts.items() if k != "target.yaml"} == {
        k: v for k, v in example.items() if k != "target.yaml"}
    index = contracts["target.yaml"]
    assert "slug: mirror\n" in index and "name: Mirror KB\n" in index and "engine: v0.1.0\n" in index
    assert _tree(workspace / "sources/inbox").keys() - {".gitkeep"} == _tree(EXAMPLE / "sources/inbox").keys()
    assert resolve_run(workspace, engine=ENGINE).contracts.slug == "mirror"


def test_an_upgrade_re_mirrors_contracts_and_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from archivist.workspace import upgrade_target

    workspace = tmp_path / "mirror"
    scaffold_workspace(workspace, MIRROR, engine="v0.1.0")
    (workspace / "contracts/scoring.yaml").write_text("version: 1\n# drifted\n", encoding="utf-8")
    (workspace / "contracts/reference/extra.yaml").write_text("x: 1\n", encoding="utf-8")
    (workspace / "sources/inbox/stray.md").write_text("stray\n", encoding="utf-8")
    (workspace / "knowledge/kept.md").write_text("kept\n", encoding="utf-8")
    registry = tmp_path / "targets.yaml"
    registry.write_text("targets:\n  - {slug: mirror, name: Mirror KB, description: d, mirrors: warehouse,"
                        " target_repo: 'https://github.com/example-org/mirror', type: test, status: active}\n",
                        encoding="utf-8")
    monkeypatch.setattr("archivist.workspace.running_version", lambda: "v1.2.3")
    result = upgrade_target(target_slug="mirror", workspace=workspace, pin="v1.2.3", registry_path=registry, local=True)
    assert "PASS  contracts valid" in result.validation
    assert (workspace / "contracts/scoring.yaml").read_text(encoding="utf-8") == (EXAMPLE / "contracts/scoring.yaml").read_text(encoding="utf-8")
    assert not (workspace / "contracts/reference/extra.yaml").exists()
    assert not (workspace / "sources/inbox/stray.md").exists()
    assert (workspace / "knowledge/kept.md").read_text(encoding="utf-8") == "kept\n"
    assert "engine: v1.2.3\n" in (workspace / "contracts/target.yaml").read_text(encoding="utf-8")


def test_mirrors_must_name_an_example(tmp_path: Path) -> None:
    from archivist.targets import TargetConfigError, load_targets

    registry = tmp_path / "targets.yaml"
    registry.write_text("targets:\n  - {slug: m, name: M, description: d, mirrors: nowhere,"
                        " target_repo: 'https://github.com/example-org/m', type: test, status: active}\n",
                        encoding="utf-8")
    with pytest.raises(TargetConfigError, match="'mirrors' names 'nowhere', which is not in examples/"):
        load_targets(registry)
