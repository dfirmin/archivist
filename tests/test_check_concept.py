"""check-concept: the deterministic frontmatter check agents run after editing a concept."""

from __future__ import annotations

from pathlib import Path

import pytest

from archivist.check_concept import check_concept

GOOD = """---
type: Runbook
title: Deploying the Web App
sources:
  - resource: sources/processed/deploy.md
    title: "FW: RE: deploy steps"
okfx_structure: routine-procedure
okfx_team: platform
---

## When To Use

*[Awaiting source material.]*

## Prerequisites

## Steps

1. Deploy.

## Verification
"""


@pytest.fixture
def concept(handbook: Path) -> Path:
    (handbook / "sources/processed").mkdir(parents=True)
    (handbook / "sources/processed/deploy.md").write_text("source\n", encoding="utf-8")
    path = handbook / "knowledge/runbooks/Deploying the Web App.md"
    path.parent.mkdir(parents=True)
    path.write_text(GOOD, encoding="utf-8")
    return path


def problems(path: Path, old: str, new: str) -> list[str]:
    path.write_text(GOOD.replace(old, new), encoding="utf-8")
    return check_concept(path).problems


def test_a_correct_concept_passes(concept: Path) -> None:
    assert check_concept(concept).ok


def test_unquoted_colons_in_a_messy_title_are_caught(concept: Path) -> None:
    found = problems(concept, 'title: "FW: RE: deploy steps"', "title: FW: RE: deploy steps")
    assert len(found) == 1 and "not valid YAML" in found[0] and "Quote" in found[0]


def test_structure_must_be_one_the_type_allows(concept: Path) -> None:
    assert problems(concept, "okfx_structure: routine-procedure", "okfx_structure: policy") == [
        "`okfx_structure: policy` is not one of runbook's structures (routine-procedure, incident-response)"
    ]
    assert "`okfx_structure` is missing" in problems(concept, "okfx_structure: routine-procedure\n", "")[0]


def test_unknown_type_and_missing_required_field(concept: Path) -> None:
    assert "is not a concept type" in problems(concept, "type: Runbook", "type: Playbook")[0]
    assert problems(concept, "okfx_team: platform\n", "") == ["required field `okfx_team` is missing or empty"]


def test_undeclared_fields_and_missing_sources_are_caught(concept: Path) -> None:
    found = problems(concept, "okfx_team: platform", "okfx_team: platform\nokfx_owner: x\nowner: y")
    assert "`okfx_owner` is not declared on concept type runbook" in found
    assert "`owner` is neither an OKF field nor an okfx_ field" in found
    found = problems(concept, "sources/processed/deploy.md", "sources/processed/missing.md")
    assert found == ["`sources[0].resource` does not exist: sources/processed/missing.md"]


QUARANTINED = """---
type: Runbook
title: Rotating the Pager
status: quarantined
sources:
  - resource: sources/quarantine/pager.md
    title: pager notes
okfx_quarantine:
  reason: The document names no owning team listed in teams.
  needs: A teams entry for the owner the document names.
---
"""


@pytest.fixture
def draft(handbook: Path) -> Path:
    (handbook / "sources/quarantine").mkdir(parents=True)
    (handbook / "sources/quarantine/pager.md").write_text("source\n", encoding="utf-8")
    path = handbook / "quarantine/pager.md"
    path.parent.mkdir(parents=True)
    path.write_text(QUARANTINED, encoding="utf-8")
    return path


def test_a_quarantined_draft_may_lack_required_fields_and_structure(draft: Path) -> None:
    assert check_concept(draft).problems == []


def test_a_quarantined_draft_says_why_and_what_resolves_it(draft: Path) -> None:
    draft.write_text(QUARANTINED.replace("  needs: A teams entry for the owner the document names.\n", ""), encoding="utf-8")
    assert check_concept(draft).problems == ["`okfx_quarantine.needs` is missing or empty"]
    draft.write_text(QUARANTINED.replace("status: quarantined", "status: draft"), encoding="utf-8")
    found = check_concept(draft).problems
    assert "a file under quarantine/ needs `status: quarantined`" in found
    assert "`okfx_quarantine` belongs only on a quarantined draft" in found


def test_a_quarantined_draft_moved_into_knowledge_is_refused(handbook: Path, draft: Path) -> None:
    moved = handbook / "knowledge/runbooks/Rotating the Pager.md"
    moved.parent.mkdir(parents=True)
    draft.rename(moved)
    found = check_concept(moved).problems
    assert any("`status: quarantined` belongs under quarantine/ only" in p and "archivist requeue" in p for p in found)


def test_placement_records_an_outcome_and_the_match(concept: Path) -> None:
    ok = "okfx_team: platform\nokfx_placement: {outcome: update, matched: 'title: Deploying the Web App'}"
    assert problems(concept, "okfx_team: platform", ok) == []
    found = problems(concept, "okfx_team: platform", "okfx_team: platform\nokfx_placement: {outcome: update}")
    assert found == ["`okfx_placement.matched` names the identity value an update matched"]
    found = problems(concept, "okfx_team: platform", "okfx_team: platform\nokfx_placement: {outcome: merge}")
    assert found == ["`okfx_placement.outcome: merge` is not one of new, update"]


def test_a_stub_for_a_document_without_a_concept_type_may_omit_type(draft: Path) -> None:
    draft.write_text(QUARANTINED.replace("type: Runbook\n", ""), encoding="utf-8")
    assert check_concept(draft).problems == []
    draft.write_text(QUARANTINED.replace("type: Runbook\n", "").replace("status: quarantined", "status: draft"),
                     encoding="utf-8")
    assert "`type` is missing (OKF requires it)" in check_concept(draft).problems


# ------------------------------------------------------------------ required headings (ADR 0010)


def test_a_missing_required_heading_is_listed(concept: Path) -> None:
    assert problems(concept, "## Verification\n", "") == [
        "required heading `## Verification` is missing (structure routine-procedure): write it per "
        "document-structure §3, as a stub `*[Awaiting source material.]*` when no source supports it"
    ]


def test_an_optional_section_may_be_absent_and_a_heading_must_match_its_level(concept: Path) -> None:
    assert check_concept(concept).ok  # Rollback is `required: false`
    assert "`## Steps` is missing" in problems(concept, "## Steps", "### Steps")[0]
    assert "`## Steps` is missing" in problems(concept, "## Steps", "## Steps to follow")[0]


def test_frontmatter_only_skips_the_body(concept: Path) -> None:
    concept.write_text(GOOD.replace("## Verification\n", ""), encoding="utf-8")
    assert check_concept(concept, frontmatter_only=True).ok


def test_a_heading_inside_a_code_block_does_not_count(concept: Path) -> None:
    assert problems(concept, "## Verification\n", "```\n## Verification\n```\n")


VIEW = """---
type: Business View Group Overview
title: Claim Header
okfx_structure: data-view-group
okfx_subject_area: claims
okfx_physical_views: [CLAIM_HDR_SV]
okfx_product_owner: claims-data@example.com
---

{body}
"""
VIEW_HEADINGS = [
    "Overview", "Source", "Data Sources & Ingestion Route", "Data Granularity",
    "Business Rules & Usage Notes", "Other Key Concepts", "Attribute Information",
    "Code Set Information", "Known Issues", "FAQ", "Glossary",
]


def _view(warehouse: Path, headings: list[str]) -> list[str]:
    path = warehouse / "knowledge/subject-areas/claims/business-views/Claim Header/overview.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(VIEW.format(body="\n\n".join(f"## {h}" for h in headings)), encoding="utf-8")
    return [p for p in check_concept(path).problems if "heading" in p]


def test_a_required_parent_of_an_optional_enricher_subtree_is_the_authors(warehouse: Path) -> None:
    # The live defect: Business Rules & Usage Notes was dropped because its only subsection
    # (optional) holds an enricher section. It is required; the subtree under it is not.
    assert _view(warehouse, VIEW_HEADINGS) == []
    found = _view(warehouse, [h for h in VIEW_HEADINGS if h != "Business Rules & Usage Notes"])
    assert len(found) == 1 and "`## Business Rules & Usage Notes`" in found[0]


def test_placeholder_sections_are_required_and_enricher_sections_are_not(warehouse: Path) -> None:
    assert "`## Glossary`" in _view(warehouse, [h for h in VIEW_HEADINGS if h != "Glossary"])[0]
    assert not any("Code-Extracted Logic" in p or "Implementation Logic" in p for p in _view(warehouse, VIEW_HEADINGS))
