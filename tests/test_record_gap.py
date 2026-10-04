"""record-gap: the one deterministic write in the gap fleet."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
import yaml

from archivist.errors import ContractError
from archivist.record_gap import record_gap
from conftest import edit_yaml

CONCEPT = """---
type: Business View Group Overview
title: Customer Case
okfx_subject_area: customer-care
---

## Overview
Body stays exactly as written.
"""


@pytest.fixture
def concept(warehouse: Path) -> Path:
    path = warehouse / "knowledge/subject-areas/customer-care/business-views/Customer Case/overview.md"
    path.parent.mkdir(parents=True)
    path.write_text(CONCEPT, encoding="utf-8")
    return path


def gaps(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n")[1]).get("okfx_gaps") or []


def test_add_update_remove_keeps_body(concept: Path) -> None:
    tricky = 'Uses "CRM": no expansion; glossary has CRM: customer relationship management.'
    assert record_gap(concept, kind="undefined_acronym", origin="author", description=tricky).action == "added"
    assert gaps(concept) == [{"kind": "undefined_acronym", "origin": "author", "description": tricky}]
    assert record_gap(concept, kind="undefined_acronym", origin="author", description=tricky).action == "unchanged"
    assert record_gap(concept, kind="undefined_acronym", origin="documentation", description="x").action == "updated"
    assert record_gap(concept, kind="undefined_acronym", absent=True).action == "removed"
    assert concept.read_text(encoding="utf-8").endswith("## Overview\nBody stays exactly as written.\n")


def test_applicability_comes_from_concept_types(concept: Path) -> None:
    text = concept.read_text(encoding="utf-8").replace("Business View Group Overview", "Subject Area Overview")
    concept.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="does not apply to 'subject-area-overview'"):
        record_gap(concept, kind="undefined_acronym", origin="author", description="x")
    record_gap(concept, kind="missing_section", origin="author", description="Known Issues is a stub.")


def test_unknown_type_disabled_kind_and_bad_origin_are_refused(concept: Path, warehouse: Path) -> None:
    with pytest.raises(ContractError, match="origin must be one of"):
        record_gap(concept, kind="missing_section", origin="sme", description="x")
    edit_yaml(warehouse / "contracts/gap-kinds.yaml", lambda d: d["kinds"][0].update({"enabled": False}))
    with pytest.raises(ContractError, match="is disabled"):
        record_gap(concept, kind="missing_section", origin="author", description="x")
    concept.write_text(CONCEPT.replace("Business View Group Overview", "Mystery"), encoding="utf-8")
    with pytest.raises(ContractError, match="concept type 'Mystery' is not in"):
        record_gap(concept, kind="undefined_acronym", origin="author", description="x")


def test_fixed_origin_is_applied(concept: Path, warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/gap-kinds.yaml", lambda d: d["kinds"][1].update({"fixed_origin": "documentation"}))
    record_gap(concept, kind="undefined_acronym", description="x")
    assert gaps(concept)[0]["origin"] == "documentation"


def _write(args: tuple[str, str]) -> str:
    path, kind = args
    return record_gap(Path(path), kind=kind, origin="author", description=f"{kind}: evidence").action


def test_concurrent_fleet_loses_no_entries(concept: Path) -> None:
    kinds = ["missing_section", "undefined_acronym", "missing_code_value_semantics", "unregistered_source_system"]
    with ProcessPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(_write, [(str(concept), k) for k in kinds * 3])).count("added") == 4
    assert sorted(g["kind"] for g in gaps(concept)) == sorted(kinds)
