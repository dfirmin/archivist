"""Engine definitions, the profile, target pipelines and the roster."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from archivist.agents import with_roster
from archivist.claude_runner import build_kickoff, prepare_agent_workspace
from archivist.engine import load_engine, resolve_run
from archivist.errors import ContractError, DefinitionError
from archivist.profile import entry_stage
from conftest import edit_yaml

ENGINE = load_engine()


def test_engine_loads_every_agent_skill_and_method() -> None:
    profile = ENGINE.profile
    assert profile.coordinator == "conductor" and profile.planner == "intake-planner"
    assert profile.stage_agents == {"author", "enricher", "verifier", "gap-agent", "scorer"}
    for agent in ENGINE.agents.values():
        assert set(agent.skills) <= set(ENGINE.skills), agent.name
    for method in profile.enrichment_methods.values():
        assert set(method["skills"]) <= set(ENGINE.skills)


def test_target_pipeline_may_reorder_and_opt_out(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/target.yaml", lambda d: d["pipelines"].update({"lean": ["author", "scorer"]}))
    run = resolve_run(warehouse, engine=ENGINE, pipeline="lean")
    assert run.roster.stages == ("author", "scorer")
    assert run.roster.spawnable == ("intake-planner", "author", "scorer")


def test_target_pipeline_cannot_name_a_non_engine_agent(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/target.yaml", lambda d: d["pipelines"].update({"x": ["author", "my-agent"]}))
    with pytest.raises(ContractError, match="'my-agent' is not an engine stage agent"):
        resolve_run(warehouse, engine=ENGINE, pipeline="x")


def test_planner_and_coordinator_are_not_stages(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/target.yaml", lambda d: d["pipelines"].update({"x": ["conductor"]}))
    with pytest.raises(ContractError, match="'conductor' is not an engine stage agent"):
        resolve_run(warehouse, engine=ENGINE, pipeline="x")


def test_target_default_pipeline_wins_over_engine_default(minimal: Path) -> None:
    assert resolve_run(minimal, engine=ENGINE).roster.pipeline == "summarize"


def test_existing_concept_drops_the_producing_stage(warehouse: Path) -> None:
    run = resolve_run(warehouse, engine=ENGINE, pipeline="full", authoring=False)
    assert run.roster.stages == ("enricher", "verifier", "gap-agent", "scorer")
    assert run.roster.support == ()
    assert entry_stage(ENGINE.profile, run.roster) == "enricher"
    assert "structures" in run.required  # the enricher still needs it


def test_authoring_run_needs_a_producing_stage(warehouse: Path) -> None:
    with pytest.raises(ContractError, match="authors nothing"):
        resolve_run(warehouse, engine=ENGINE, pipeline="gaps", authoring=True)


def test_unknown_pipeline_lists_the_defined_ones(minimal: Path) -> None:
    with pytest.raises(ContractError, match=r"unknown pipeline 'nope' \(defined: .*summarize"):
        resolve_run(minimal, engine=ENGINE, pipeline="nope")


def test_coordinator_roster_replaces_bare_agent_tool() -> None:
    assert with_roster(("Agent", "Read"), ("author",), label="c") == ("Agent(author)", "Read")
    with pytest.raises(DefinitionError):
        with_roster(("Agent(author)",), ("author",), label="c")


def test_prepare_workspace_installs_engine_and_plan(warehouse: Path) -> None:
    prepared = prepare_agent_workspace(warehouse, pipeline="no-code")
    conductor = (warehouse / ".claude/agents/conductor.md").read_text(encoding="utf-8")
    assert "Agent(intake-planner, author, verifier, gap-agent, scorer)" in conductor
    assert (warehouse / ".claude/skills/target-contracts/SKILL.md").is_file()
    plan = yaml.safe_load(prepared.plan.read_text(encoding="utf-8"))
    assert [s["agent"] for s in plan["stages"]] == ["author", "verifier", "gap-agent", "scorer"]
    assert plan["entry_stage"] == "author"
    assert plan["contracts"]["gap-kinds"] == "contracts/gap-kinds.yaml"
    assert plan["reference"]["inventory"]["path"] == "contracts/reference/inventory.csv"
    assert plan["stages"][2]["dispatch"]["per"] == "gap-kind"


def test_kickoff_names_plan_stages_and_publish() -> None:
    text = build_kickoff(inbox_file="sources/inbox/a.md", stages=("author", "verifier"),
                         pipeline="summarize", branch="archivist/a")
    assert "author the inbox document `sources/inbox/a.md`" in text
    assert "Plan: `.claude/archivist/run-plan.yaml` (pipeline `summarize`)" in text
    assert "Stages: author, verifier." in text
    assert "Publish: yes, on branch `archivist/a`." in text
    assert "Leave git alone" in build_kickoff(skip_publish=True)
    resumed = build_kickoff(branch="archivist/run-1", continue_branch=True)
    assert "already created and pushed. Check it out; do not recreate it." in resumed


DOMAIN_WORDS = ("subject area", "subject-area", "business view", "business-view", "physical view",
                "warehouse", "okfx_subject", "okfx_physical", "okfx_code_repo", "okfx_product_owner")
METHOD_SKILLS = {s for m in ENGINE.profile.enrichment_methods.values() for s in m["skills"]}


def test_engine_agents_and_core_skills_name_no_domain() -> None:
    """Rule 4 in AGENTS.md: domain lives in contracts. Method skills may be technology-specific."""
    files = [a.path for a in ENGINE.agents.values()]
    files += [s.path / "SKILL.md" for s in ENGINE.skills.values() if s.name not in METHOD_SKILLS]
    files += sorted((Path(__file__).parents[1] / "src/archivist").glob("*.py"))
    offenders = [
        f"{path.name}: {word}"
        for path in files
        for word in DOMAIN_WORDS
        if word in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []
