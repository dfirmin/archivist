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
