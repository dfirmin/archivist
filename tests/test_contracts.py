"""Contract guardrails: presence, syntax, schema, cross-references, okfx_ prefix, requirements."""

from __future__ import annotations

from pathlib import Path

import pytest

from archivist.contracts import load_contracts
from archivist.engine import load_engine, resolve_run
from archivist.errors import ContractError, WorkspaceError
from conftest import edit_yaml

ENGINE = load_engine()
METHODS = ENGINE.profile.enrichment_methods


def contracts_error(workspace: Path) -> str:
    with pytest.raises(ContractError) as exc:
        load_contracts(workspace, enrichment_methods=METHODS)
    return str(exc.value)


@pytest.mark.parametrize("pipeline", ["full", "no-code", "gaps", "author-verify", "enrich"])
def test_warehouse_example_is_valid_for_every_pipeline(warehouse: Path, pipeline: str) -> None:
    run = resolve_run(warehouse, engine=ENGINE, pipeline=pipeline)
    assert run.roster.pipeline == pipeline


def test_minimal_example_needs_only_what_its_pipeline_uses(minimal: Path) -> None:
    run = resolve_run(minimal, engine=ENGINE)
    assert run.roster.stages == ("author", "verifier")
    assert set(run.required) == {"concept-types", "structures"}


def test_pipeline_requirements_are_enforced(minimal: Path) -> None:
    with pytest.raises(ContractError, match=r"gap-kinds \(needed by gap-agent, scorer\).*scoring"):
        resolve_run(minimal, engine=ENGINE, pipeline="gaps", authoring=False)


def test_missing_index_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="contracts/target.yaml not found"):
        load_contracts(tmp_path)


def test_declared_file_must_exist_and_stay_inside_contracts(minimal: Path) -> None:
    edit_yaml(minimal / "contracts/target.yaml", lambda d: d["contracts"].update({"scoring": "../scoring.yaml"}))
    assert "without '..'" in contracts_error(minimal)
    edit_yaml(minimal / "contracts/target.yaml", lambda d: d["contracts"].update({"scoring": "scoring.yaml"}))
    assert "file not found: contracts/scoring.yaml" in contracts_error(minimal)


def test_unknown_contract_kind_is_a_schema_error(minimal: Path) -> None:
    edit_yaml(minimal / "contracts/target.yaml", lambda d: d["contracts"].update({"archetypes": "x.yaml"}))
    assert "'archetypes' was unexpected" in contracts_error(minimal)


def test_invalid_yaml_is_reported_with_its_file(minimal: Path) -> None:
    (minimal / "contracts/concept-types.yaml").write_text("version: 1\nconcept_types: [\n", encoding="utf-8")
    assert "contracts/concept-types.yaml: invalid YAML" in contracts_error(minimal)


def test_non_okf_fields_need_the_okfx_prefix(minimal: Path) -> None:
    def add(d):  # type: ignore[no-untyped-def]
        d["concept_types"]["policy-summary"]["fields"]["policy_owner"] = {"description": "x"}
        d["concept_types"]["policy-summary"]["fields"]["status"] = {"description": "OKF field: allowed"}

    edit_yaml(minimal / "contracts/concept-types.yaml", add)
    message = contracts_error(minimal)
    assert "fields.policy_owner: not an OKF field, so it must start with 'okfx_'" in message
    assert "fields.status" not in message


def test_engine_fields_cannot_be_declared(minimal: Path) -> None:
    edit_yaml(
        minimal / "contracts/concept-types.yaml",
        lambda d: d["concept_types"]["policy-summary"]["fields"].update({"okfx_confidence": {"description": "x"}}),
    )
    assert "okfx_confidence: engine-owned field" in contracts_error(minimal)


def test_okf_type_strings_are_unique(warehouse: Path) -> None:
    edit_yaml(
        warehouse / "contracts/concept-types.yaml",
        lambda d: d["concept_types"]["reference"].update({"type": "View"}),
    )
    assert "type 'View' is also used by 'physical-view'" in contracts_error(warehouse)


def test_concept_type_structure_must_exist(minimal: Path) -> None:
    edit_yaml(
        minimal / "contracts/concept-types.yaml",
        lambda d: d["concept_types"]["policy-summary"].update({"structures": ["missing"]}),
    )
    assert "structure 'missing' not found" in contracts_error(minimal)


def test_structure_id_must_match_file_name(minimal: Path) -> None:
    edit_yaml(minimal / "contracts/structures/policy-summary.yaml", lambda d: d.update({"id": "other"}))
    assert "must equal the file name 'policy-summary'" in contracts_error(minimal)


def test_section_ownership_rules(minimal: Path) -> None:
    def change(d):  # type: ignore[no-untyped-def]
        d["sections"].append({"heading": "Lineage", "owner": "enricher"})
        d["sections"].append({"heading": "Notes", "owner": "placeholder"})
        d["sections"].append("Purpose")

    edit_yaml(minimal / "contracts/structures/policy-summary.yaml", change)
    message = contracts_error(minimal)
    assert "## Lineage: owner enricher needs an enrich block" in message
    assert "## Notes: owner placeholder needs placeholder text" in message
    assert "## Purpose: heading is listed twice" in message


def test_enrich_method_and_lookup_must_resolve(warehouse: Path) -> None:
    def change(d):  # type: ignore[no-untyped-def]
        enrich = d["sections"][4]["subsections"][0]["subsections"][0]["enrich"]
        enrich["method"] = "lineage-graph"
        enrich["lookup"] = "repos"

    edit_yaml(warehouse / "contracts/structures/data-view-group.yaml", change)
    message = contracts_error(warehouse)
    assert "enrich.method 'lineage-graph' is not an engine method (code-logic)" in message
    assert "enrich.lookup 'repos' is not a reference contract" in message


def test_intake_routes_only_to_existing_sections(warehouse: Path) -> None:
    edit_yaml(
        warehouse / "contracts/intake.yaml",
        lambda d: d["classes"][1].update({"sections": ["Attribute Info"]}),
    )
    assert "routes to 'Attribute Info', which no structure of 'business-view-group-overview' has" in contracts_error(warehouse)


def test_intake_concept_type_must_be_authored(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/intake.yaml", lambda d: d.update({"concept_type": "physical-view"}))
    assert "is not authored: true" in contracts_error(warehouse)


def test_gap_kind_cross_references(warehouse: Path) -> None:
    def change(d):  # type: ignore[no-untyped-def]
        kind = d["kinds"][0]
        kind["applies_to"] = ["view-group"]
        kind["priority"] = "urgent"
        kind["origins"] = ["author", "sme"]
        kind["uses"] = ["thesaurus"]

    edit_yaml(warehouse / "contracts/gap-kinds.yaml", change)
    message = contracts_error(warehouse)
    assert "applies_to 'view-group' is not a concept type" in message
    assert "priority 'urgent'" in message
    assert "origin 'sme'" in message
    assert "uses 'thesaurus'" in message


def test_gap_kinds_may_define_their_own_origins_and_priorities(warehouse: Path) -> None:
    def change(d):  # type: ignore[no-untyped-def]
        d["origins"] = {"author": "a", "documentation": "b", "sme": "Needs a subject-matter expert."}
        d["priorities"] = ["p3", "p2", "p1"]
        for kind in d["kinds"]:
            kind["priority"] = "p2"
        d["kinds"][0]["origins"] = ["sme"]

    edit_yaml(warehouse / "contracts/gap-kinds.yaml", change)
    load_contracts(warehouse, enrichment_methods=METHODS)


def test_scoring_bands_sit_inside_the_scale(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/scoring.yaml", lambda d: d["bands"][0].update({"max": 1.5}))
    assert "bands[0] must sit inside the scale" in contracts_error(warehouse)


def test_publishing_title_needs_kind(warehouse: Path) -> None:
    edit_yaml(warehouse / "contracts/publishing.yaml", lambda d: d["issues"].update({"title": "{title}"}))
    assert "issues.title must contain {kind}" in contracts_error(warehouse)


def test_reference_csv_header_must_match_columns(warehouse: Path) -> None:
    path = warehouse / "contracts/reference/inventory.csv"
    path.write_text("entity,area,repo\nX,customer-care,\n", encoding="utf-8")
    assert "does not match columns ['entity', 'subject_area', 'source_repo']" in contracts_error(warehouse)


def test_reference_schema_is_applied(warehouse: Path) -> None:
    edit_yaml(
        warehouse / "contracts/reference/owners.yaml",
        lambda d: d["subject_areas"][0].update({"archetype": "warehouse"}),
    )
    assert "contracts/reference/owners.yaml: subject_areas.0.archetype" in contracts_error(warehouse)


def test_custom_reference_data_needs_no_engine_change(minimal: Path) -> None:
    (minimal / "contracts/reference").mkdir()
    (minimal / "contracts/reference/approvers.yaml").write_text("approvers: {hr: hr@example.com}\n", encoding="utf-8")
    edit_yaml(
        minimal / "contracts/target.yaml",
        lambda d: d.update(
            {"reference": {"approvers": {"path": "reference/approvers.yaml", "description": "Who approves what."}}}
        ),
    )
    contracts = load_contracts(minimal)
    assert contracts.references["approvers"].rel == "contracts/reference/approvers.yaml"
    assert "reference" in contracts.declared


def test_all_problems_are_reported_at_once(minimal: Path) -> None:
    def change(d):  # type: ignore[no-untyped-def]
        d["concept_types"]["policy-summary"]["fields"]["owner"] = {"description": "x"}
        d["concept_types"]["policy-summary"]["structures"] = ["nope"]

    edit_yaml(minimal / "contracts/concept-types.yaml", change)
    message = contracts_error(minimal)
    assert "must start with 'okfx_'" in message and "structure 'nope' not found" in message


def test_targets_cannot_ship_agents(minimal: Path) -> None:
    (minimal / "agents").mkdir()
    with pytest.raises(WorkspaceError, match="targets define contracts only"):
        resolve_run(minimal, engine=ENGINE)


def test_slug_must_match_the_registry(minimal: Path) -> None:
    with pytest.raises(ContractError, match="does not match target 'other'"):
        resolve_run(minimal, engine=ENGINE, expected_slug="other")
