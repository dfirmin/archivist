"""Runs on existing concepts (ADR 0004): scope resolution, prune-gaps and the write fence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import edit_yaml

from archivist.claude_runner import (
    build_kickoff,
    prepare_agent_workspace,
    run_conductor_agent,
)
from archivist.contracts import load_contracts
from archivist.engine import load_engine, resolve_run
from archivist.profile import fenced_fields
from archivist.record_gap import prune_gaps, record_gap
from archivist.scope import ScopeError, batches, fence_violations, select, snapshot

ENGINE = load_engine()
GROUP = "knowledge/subject-areas/customer-care/business-views/Customer Case/overview.md"
AREA = "knowledge/subject-areas/customer-care/overview.md"


def write(root: Path, rel: str, okf_type: str, body: str = "## Overview\nBody.\n", extra: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: {okf_type}\ntitle: T\n{extra}---\n\n{body}", encoding="utf-8")
    return path


def frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


@pytest.fixture
def corpus(warehouse: Path) -> Path:
    write(warehouse, GROUP, "Business View Group Overview")
    write(warehouse, AREA, "Subject Area Overview")
    write(warehouse, "knowledge/notes/readme.md", "Not A Concept Type")
    write(warehouse, "knowledge/subject-areas/customer-care/business-views/Customer Case/v.md", "View")
    return warehouse


def stages(workspace: Path, pipeline: str) -> tuple[str, ...]:
    return resolve_run(workspace, engine=ENGINE, pipeline=pipeline, authoring=False).roster.stages


# ----------------------------------------------------------------------------- scope


def test_all_selects_every_published_concept(corpus: Path) -> None:
    sel = select(corpus, load_contracts(corpus), concepts=["all"], stages=stages(corpus, "gaps"))
    assert sel.concepts == (GROUP, AREA)  # path order
    assert sel.kinds is None


def test_kind_scope_skips_concepts_it_does_not_apply_to(corpus: Path) -> None:
    sel = select(corpus, load_contracts(corpus), concepts=["all"], kinds=["undefined_acronym"],
                 stages=stages(corpus, "gaps"))
    assert sel.concepts == (GROUP,)
    assert sel.skipped == ((AREA, "no kind in scope applies to subject-area-overview"),)


def test_unknown_or_disabled_kinds_are_refused(corpus: Path) -> None:
    contracts = load_contracts(corpus)
    with pytest.raises(ScopeError, match="not in"):
        select(corpus, contracts, concepts=["all"], kinds=["nope"], stages=stages(corpus, "gaps"))
    edit_yaml(corpus / "contracts/gap-kinds.yaml",
              lambda d: d["kinds"][1].__setitem__("enabled", False))
    with pytest.raises(ScopeError, match="disabled"):
        select(corpus, load_contracts(corpus), concepts=["all"], kinds=["undefined_acronym"],
               stages=stages(corpus, "gaps"))


def test_kind_needs_a_gap_stage(corpus: Path) -> None:
    with pytest.raises(ScopeError, match="gap-agent"):
        select(corpus, load_contracts(corpus), concepts=["all"], kinds=["missing_section"],
               stages=stages(corpus, "rescore"))


def test_named_concepts_must_be_concepts(corpus: Path) -> None:
    contracts = load_contracts(corpus)
    with pytest.raises(ScopeError, match="not a concept type"):
        select(corpus, contracts, concepts=["knowledge/notes/readme.md"], stages=("scorer",))
    with pytest.raises(ScopeError, match="not found"):
        select(corpus, contracts, concepts=["knowledge/missing.md"], stages=("scorer",))
    with pytest.raises(ScopeError, match="does not combine"):
        select(corpus, contracts, concepts=["all", GROUP], stages=("scorer",))


def test_batches_split_in_order() -> None:
    assert batches(["a", "b", "c"], 2) == [("a", "b"), ("c",)]


def test_plan_and_kickoff_carry_the_scope(corpus: Path) -> None:
    prepared = prepare_agent_workspace(corpus, pipeline="gaps", authoring=False, kinds=["missing_section"])
    plan = yaml.safe_load(prepared.plan.read_text(encoding="utf-8"))
    assert plan["scope"] == {"kinds": ["missing_section"]}
    assert "prune-gaps" in plan["stages"][0]["dispatch"]["before"]
    text = build_kickoff(concept_files=[AREA, GROUP], kinds=["missing_section"], skip_publish=True)
    assert "these 2 existing concepts, one group each" in text and f"- `{GROUP}`" in text
    assert "Gap kinds: only missing_section" in text


def test_kind_without_concepts_and_empty_scope(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_conductor_agent(workspace=corpus, kinds=["missing_section"]) == 1
    assert "--kind applies to runs on existing concepts" in capsys.readouterr().err
    # Nothing applicable: a clean exit before any session (or auth) is needed.
    edit_yaml(corpus / "contracts/gap-kinds.yaml",
              lambda d: d["kinds"][1].__setitem__("applies_to", ["subject-area-overview"]))
    code = run_conductor_agent(workspace=corpus, pipeline="gaps", concept_files=[GROUP],
                               kinds=["undefined_acronym"], skip_publish=True)
    assert code == 0
    assert "nothing in scope" in capsys.readouterr().out


# ------------------------------------------------------------------------- prune-gaps


def test_prune_drops_only_unsupported_kinds_and_keeps_the_body(corpus: Path) -> None:
    concept = corpus / GROUP
    record_gap(concept, kind="missing_section", origin="documentation", description="a")
    record_gap(concept, kind="undefined_acronym", origin="documentation", description="b")
    record_gap(concept, kind="unregistered_source_system", origin="author", description="c")

    def change(doc: dict) -> None:
        doc["kinds"] = [k for k in doc["kinds"] if k["id"] != "undefined_acronym"]  # removed
        for k in doc["kinds"]:
            if k["id"] == "unregistered_source_system":
                k["applies_to"] = ["subject-area-overview"]  # no longer applies

    edit_yaml(corpus / "contracts/gap-kinds.yaml", change)
    result = prune_gaps(concept)
    assert result.removed == ("undefined_acronym", "unregistered_source_system")
    assert [g["kind"] for g in frontmatter(concept)["okfx_gaps"]] == ["missing_section"]
    assert concept.read_text(encoding="utf-8").endswith("## Overview\nBody.\n")
    assert prune_gaps(concept).removed == ()


def test_prune_adds_an_empty_list_when_missing(corpus: Path) -> None:
    concept = corpus / AREA
    assert prune_gaps(concept).created
    assert frontmatter(concept)["okfx_gaps"] == []
    assert not prune_gaps(concept).created


# ------------------------------------------------------------------------ write fence


def test_fence_covers_field_only_pipelines(corpus: Path) -> None:
    def fence(pipeline: str):  # type: ignore[no-untyped-def]
        run = resolve_run(corpus, engine=ENGINE, pipeline=pipeline, authoring=False)
        return fenced_fields(ENGINE.profile, run.roster)

    assert fence("gaps") == {"okfx_gaps", "okfx_confidence"}
    assert fence("rescore") == {"okfx_confidence"}
    assert fence("full") is None  # the verifier writes bodies


def test_fence_allows_declared_fields_on_scoped_concepts(corpus: Path) -> None:
    before = snapshot(corpus)
    record_gap(corpus / GROUP, kind="missing_section", origin="documentation", description="a")
    assert fence_violations(before, snapshot(corpus), scope=[GROUP], fields={"okfx_gaps"}) == []


def test_fence_reports_body_fields_scope_and_new_files(corpus: Path) -> None:
    before = snapshot(corpus)
    group = corpus / GROUP
    group.write_text(group.read_text(encoding="utf-8").replace("Body.", "Rewritten."), encoding="utf-8")
    area = corpus / AREA
    area.write_text(area.read_text(encoding="utf-8").replace("title: T", "title: New"), encoding="utf-8")
    write(corpus, "knowledge/extra.md", "Subject Area Overview")
    problems = fence_violations(before, snapshot(corpus), scope=[GROUP], fields={"okfx_gaps"})
    assert f"{GROUP}: body changed" in problems
    assert f"{AREA}: changed, but it is not in this session's scope" in problems
    assert "knowledge/extra.md: created" in problems
    in_scope = fence_violations(before, snapshot(corpus), scope=[GROUP, AREA], fields={"okfx_gaps"})
    assert any(p.startswith(f"{AREA}: frontmatter field(s)") and p.endswith("title") for p in in_scope)
