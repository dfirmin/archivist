"""Target contracts: ``contracts/target.yaml`` and every file it declares.

A target owns the *what* — concept types, document structures, intake rules, gap kinds,
scoring, catalog and publishing conventions, and any reference data of its own. Agents read
and apply those files. This module is the guardrail around them, nothing more:

- the index exists and every declared file exists, stays inside ``contracts/`` and parses;
- each built-in contract satisfies its JSON Schema under ``schemas/contracts/``;
- cross-references resolve (a concept type's structure exists, a gap kind's ``applies_to``
  names a concept type, an enrichment method exists in the engine profile, …);
- frontmatter fields outside the OKF standard carry the ``okfx_`` prefix;
- the contracts a pipeline's agents ``require`` are declared (``check_requirements``).

It never interprets prose (``guidance``, ``scope``, ``grouping`` …): that is agent work.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import yaml
from jsonschema import Draft202012Validator

from archivist.errors import ContractError, WorkspaceError

CONTRACTS_DIR = "contracts"
INDEX_FILE = "target.yaml"
INDEX_REL = f"{CONTRACTS_DIR}/{INDEX_FILE}"

FILE_KINDS = ("concept-types", "intake", "gap-kinds", "scoring", "catalog", "publishing")
DIR_KINDS = ("structures",)
BUILTIN_KINDS = (*FILE_KINDS, *DIR_KINDS)
REFERENCE = "reference"  # a requirement on "any reference data"; never a required kind

# Concept frontmatter keys the OKF v0.2 spec defines. Anything else a target declares must
# start with ``okfx_`` so a reader can tell standard from extension at a glance.
OKF_FIELDS = frozenset(
    {
        "type", "title", "description", "resource", "tags", "sources", "usage_window",
        "generated", "verified", "status", "stale_after", "runtime", "parameters",
        "computation", "executor", "attester",
    }
)
EXTENSION_PREFIX = "okfx_"
GAPS_FIELD = "okfx_gaps"
CONFIDENCE_FIELD = "okfx_confidence"
STRUCTURE_FIELD = "okfx_structure"  # the structure the author chose; later stages read it
PLACEMENT_FIELD = "okfx_placement"  # new or update, and the concept matched (ADR 0005)
QUARANTINE_FIELD = "okfx_quarantine"  # why a draft could not be placed, and what would resolve it
ENGINE_FIELDS = frozenset({GAPS_FIELD, CONFIDENCE_FIELD, STRUCTURE_FIELD, PLACEMENT_FIELD, QUARANTINE_FIELD})
IDENTITY_TITLE = "title"  # the one OKF field an identity may name besides declared fields

DEFAULT_ORIGINS: Mapping[str, str] = {
    "author": "A cited source or a reference contract holds the information, but the concept "
    "omitted or misstated it.",
    "documentation": "The source material lacks the information, or it needs an owner's decision.",
}
DEFAULT_PRIORITIES = ("low", "medium", "high")


# ------------------------------------------------------------------------------ model


@dataclass(frozen=True, slots=True)
class Reference:
    name: str
    path: Path
    rel: str
    description: str
    guidance: str | None = None
    schema: Path | None = None
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetContracts:
    workspace: Path
    index: dict[str, Any]
    paths: dict[str, Path]
    documents: dict[str, Any]
    references: dict[str, Reference] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return str(self.index["slug"])

    @property
    def declared(self) -> frozenset[str]:
        kinds = set(self.paths)
        if self.references:
            kinds.add(REFERENCE)
        return frozenset(kinds)

    @property
    def pipelines(self) -> dict[str, tuple[str, ...]]:
        return {name: tuple(stages) for name, stages in (self.index.get("pipelines") or {}).items()}

    @property
    def default_pipeline(self) -> str | None:
        return self.index.get("default_pipeline")

    def rel(self, kind: str) -> str:
        return self.paths[kind].relative_to(self.workspace).as_posix()

    def concept_types(self) -> dict[str, dict[str, Any]]:
        doc = self.documents.get("concept-types") or {}
        return dict(doc.get("concept_types") or {})

    def concept_type_id(self, okf_type: str) -> str | None:
        """The concept type id whose OKF ``type`` equals ``okf_type``."""
        for type_id, spec in self.concept_types().items():
            if spec.get("type") == okf_type:
                return type_id
        return None

    def structures(self) -> dict[str, dict[str, Any]]:
        return dict(self.documents.get("structures") or {})

    def gap_kinds(self) -> dict[str, Any]:
        return dict(self.documents.get("gap-kinds") or {})


# ---------------------------------------------------------------------------- schemas


def schemas_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "contracts"


@cache
def _validator(name: str) -> Draft202012Validator:
    path = schemas_root() / f"{name}.schema.json"
    if not path.is_file():
        raise ContractError(f"engine schema not found: {path}")
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _schema_errors(validator: Draft202012Validator, document: Any, label: str) -> list[str]:
    out = []
    for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{label}: {loc}: {err.message}")
    return out


# ------------------------------------------------------------------------------ files


def _inside(base: Path, rel: str, label: str) -> Path:
    if Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ContractError(f"{label}: path must be relative to {CONTRACTS_DIR}/ without '..': {rel!r}")
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ContractError(f"{label}: path escapes {CONTRACTS_DIR}/: {rel!r}")
    return path


def _read_yaml(path: Path, label: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"{label}: invalid YAML: {exc}") from exc


def _read_data(path: Path, label: str) -> Any:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        return _read_yaml(path, label)
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{label}: invalid JSON: {exc}") from exc
    if suffix == ".csv":
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error as exc:
            raise ContractError(f"{label}: invalid CSV: {exc}") from exc
        return [row for row in rows if row and not row[0].lstrip().startswith("#")]
    return text


def section_dicts(sections: Iterable[Any]) -> Iterator[dict[str, Any]]:
    """Normalize a structure's section list: a bare string is ``{heading: <string>}``."""
    for item in sections or ():
        yield {"heading": item} if isinstance(item, str) else item


def iter_sections(sections: Iterable[Any], level: int = 2) -> Iterator[tuple[int, dict[str, Any]]]:
    """Every section at every depth with its Markdown heading level (## is 2)."""
    for section in section_dicts(sections):
        yield level, section
        yield from iter_sections(section.get("subsections") or (), level + 1)


# ------------------------------------------------------------------------------- load


def contracts_root(workspace: Path) -> Path:
    return workspace / CONTRACTS_DIR


def load_contracts(
    workspace: Path,
    *,
    enrichment_methods: Iterable[str] | None = None,
) -> TargetContracts:
    """Load and validate every contract the index declares. Reports all problems at once."""
    workspace = workspace.resolve()
    base = contracts_root(workspace)
    index_path = base / INDEX_FILE
    if not index_path.is_file():
        raise ContractError(f"{INDEX_REL} not found: a target ships its contract index there")
    index = _read_yaml(index_path, INDEX_REL)
    if not isinstance(index, dict):
        raise ContractError(f"{INDEX_REL} must be a YAML mapping")
    errors = _schema_errors(_validator("target"), index, INDEX_REL)
    if errors:
        raise ContractError("\n".join(errors))

    paths: dict[str, Path] = {}
    documents: dict[str, Any] = {}
    for kind, rel in (index.get("contracts") or {}).items():
        label = f"{INDEX_REL}: contracts.{kind}"
        try:
            path = _inside(base, rel, label)
        except ContractError as exc:
            errors.append(str(exc))
            continue
        if kind in DIR_KINDS:
            if not path.is_dir():
                errors.append(f"{label}: directory not found: {CONTRACTS_DIR}/{rel}")
                continue
            paths[kind] = path
            documents[kind] = _load_structures(path, workspace, errors)
        else:
            if not path.is_file():
                errors.append(f"{label}: file not found: {CONTRACTS_DIR}/{rel}")
                continue
            paths[kind] = path
            doc_label = path.relative_to(workspace).as_posix()
            try:
                document = _read_yaml(path, doc_label)
            except ContractError as exc:
                errors.append(str(exc))
                continue
            schema_errors = _schema_errors(_validator(kind), document, doc_label)
            errors.extend(schema_errors)
            if not schema_errors:
                documents[kind] = document

    references = _load_references(index.get("reference") or {}, base, workspace, errors)
    contracts = TargetContracts(workspace, index, paths, documents, references)
    errors.extend(_cross_check(contracts, enrichment_methods))
    if errors:
        raise ContractError("\n".join(errors))
    return contracts


def _load_structures(directory: Path, workspace: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    if not files:
        errors.append(f"{directory.relative_to(workspace).as_posix()}: no structure files")
    for path in files:
        label = path.relative_to(workspace).as_posix()
        try:
            document = _read_yaml(path, label)
        except ContractError as exc:
            errors.append(str(exc))
            continue
        schema_errors = _schema_errors(_validator("structure"), document, label)
        if schema_errors:
            errors.extend(schema_errors)
            continue
        if document["id"] != path.stem:
            errors.append(f"{label}: id {document['id']!r} must equal the file name {path.stem!r}")
            continue
        found[document["id"]] = document
    return found


def _load_references(
    raw: dict[str, Any], base: Path, workspace: Path, errors: list[str]
) -> dict[str, Reference]:
    out: dict[str, Reference] = {}
    for name, spec in raw.items():
        label = f"{INDEX_REL}: reference.{name}"
        try:
            path = _inside(base, spec["path"], label)
            schema = _inside(base, spec["schema"], f"{label}.schema") if spec.get("schema") else None
        except ContractError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"{label}: file not found: {CONTRACTS_DIR}/{spec['path']}")
            continue
        rel = path.relative_to(workspace).as_posix()
        try:
            data = _read_data(path, rel)
        except ContractError as exc:
            errors.append(str(exc))
            continue
        columns = tuple(spec.get("columns") or ())
        if columns:
            if path.suffix.lower() != ".csv":
                errors.append(f"{label}: columns apply to CSV files only")
            elif not data or tuple(c.strip() for c in data[0]) != columns:
                header = tuple(c.strip() for c in data[0]) if data else ()
                errors.append(f"{rel}: header {list(header)} does not match columns {list(columns)}")
        if schema is not None:
            if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                errors.append(f"{label}: schema applies to YAML or JSON files only")
            elif not schema.is_file():
                errors.append(f"{label}: schema not found: {CONTRACTS_DIR}/{spec['schema']}")
            else:
                try:
                    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
                except json.JSONDecodeError as exc:
                    errors.append(f"{label}: schema is invalid JSON: {exc}")
                else:
                    errors.extend(_schema_errors(validator, data, rel))
        out[name] = Reference(
            name=name,
            path=path,
            rel=rel,
            description=spec["description"],
            guidance=spec.get("guidance"),
            schema=schema,
            columns=columns,
        )
    return out


# ------------------------------------------------------------------------ cross-check


def _cross_check(c: TargetContracts, enrichment_methods: Iterable[str] | None) -> list[str]:
    errors: list[str] = []
    types = c.concept_types()
    structures = c.structures()
    refs = set(c.references)
    methods = set(enrichment_methods) if enrichment_methods is not None else None

    if "concept-types" in c.documents:
        label = c.rel("concept-types")
        seen_types: dict[str, str] = {}
        for type_id, spec in types.items():
            where = f"{label}: concept_types.{type_id}"
            okf_type = spec["type"]
            if okf_type in seen_types:
                errors.append(f"{where}: type {okf_type!r} is also used by {seen_types[okf_type]!r}")
            seen_types[okf_type] = type_id
            for name in spec.get("fields") or {}:
                if name in OKF_FIELDS:
                    continue
                if name in ENGINE_FIELDS:
                    errors.append(f"{where}.fields.{name}: engine-owned field; do not declare it")
                elif not name.startswith(EXTENSION_PREFIX):
                    errors.append(
                        f"{where}.fields.{name}: not an OKF field, so it must start with "
                        f"{EXTENSION_PREFIX!r}"
                    )
            for sid in spec.get("structures") or ():
                if "structures" not in c.paths:
                    errors.append(f"{where}: names structure {sid!r} but no structures contract is declared")
                    break
                if sid not in structures:
                    errors.append(f"{where}: structure {sid!r} not found")
            if len(spec.get("structures") or ()) > 1 and not spec.get("structure_rule"):
                errors.append(f"{where}: several structures need a structure_rule")
            if spec.get("authored") and not (spec.get("path") and spec.get("structures")):
                errors.append(f"{where}: an authored type needs a path and structures")
            for name in (spec.get("identity") or {}).get("fields") or ():
                if name != IDENTITY_TITLE and name not in (spec.get("fields") or {}):
                    errors.append(
                        f"{where}.identity: field {name!r} is not a declared field of the type "
                        f"(or {IDENTITY_TITLE!r})"
                    )
            for i, comp in enumerate(spec.get("companions") or ()):
                if comp["concept_type"] not in types:
                    errors.append(f"{where}.companions[{i}]: concept type {comp['concept_type']!r} not found")
                if comp["for_each"] not in (spec.get("fields") or {}):
                    errors.append(f"{where}.companions[{i}]: for_each {comp['for_each']!r} is not a declared field")

    for sid, doc in structures.items():
        label = f"{c.rel('structures')}/{sid}"
        errors.extend(_check_sections(doc["sections"], label, refs, methods, parent=""))

    if "intake" in c.documents:
        label = c.rel("intake")
        intake = c.documents["intake"]
        default = intake.get("concept_type")
        classes = intake.get("classes") or ()

        def check_type(type_id: str, where: str) -> dict[str, Any] | None:
            spec = types.get(type_id)
            if spec is None:
                errors.append(f"{label}: {where} concept_type {type_id!r} not found")
            elif not spec.get("authored"):
                errors.append(f"{label}: {where} concept_type {type_id!r} is not authored: true")
            else:
                return spec
            return None

        if "concept-types" not in c.documents:
            errors.append(f"{label}: needs a concept-types contract")
        else:
            if default:
                check_type(default, "default")
            elif not classes:
                errors.append(f"{label}: give a default concept_type, or classes that each name one")
            ids: set[str] = set()
            for cls in classes:
                if cls["id"] in ids:
                    errors.append(f"{label}: class {cls['id']!r} is listed twice")
                ids.add(cls["id"])
                type_id = cls.get("concept_type") or default
                if not type_id:
                    errors.append(f"{label}: class {cls['id']!r} names no concept_type and there is no default")
                    continue
                spec = check_type(type_id, f"class {cls['id']!r}") if cls.get("concept_type") else types.get(type_id)
                if spec is None or not isinstance(cls.get("sections"), list):
                    continue
                headings = {
                    s["heading"]
                    for sid in spec.get("structures") or ()
                    if sid in structures
                    for _, s in iter_sections(structures[sid]["sections"])
                }
                for heading in cls["sections"]:
                    if heading not in headings:
                        errors.append(
                            f"{label}: class {cls['id']!r} routes to {heading!r}, which no "
                            f"structure of {type_id!r} has"
                        )

    if "gap-kinds" in c.documents:
        label = c.rel("gap-kinds")
        doc = c.documents["gap-kinds"]
        origins = set((doc.get("origins") or DEFAULT_ORIGINS).keys())
        priorities = set(doc.get("priorities") or DEFAULT_PRIORITIES)
        seen: set[str] = set()
        for kind in doc["kinds"]:
            where = f"{label}: kind {kind['id']!r}"
            if kind["id"] in seen:
                errors.append(f"{where}: id is listed twice")
            seen.add(kind["id"])
            if "concept-types" not in c.documents:
                errors.append(f"{where}: applies_to needs a concept-types contract")
            else:
                for type_id in kind["applies_to"]:
                    if type_id not in types:
                        errors.append(f"{where}: applies_to {type_id!r} is not a concept type")
            for origin in kind["origins"]:
                if origin not in origins:
                    errors.append(f"{where}: origin {origin!r} is not one of {sorted(origins)}")
            if kind.get("fixed_origin") and kind["fixed_origin"] not in kind["origins"]:
                errors.append(f"{where}: fixed_origin must be one of its origins")
            if kind["priority"] not in priorities:
                errors.append(f"{where}: priority {kind['priority']!r} is not one of {sorted(priorities)}")
            for name in kind.get("uses") or ():
                if name not in refs:
                    errors.append(f"{where}: uses {name!r}, which is not a reference contract")

    if "scoring" in c.documents:
        label = c.rel("scoring")
        doc = c.documents["scoring"]
        lo, hi = doc["scale"]["min"], doc["scale"]["max"]
        if lo >= hi:
            errors.append(f"{label}: scale.min must be below scale.max")
        for i, band in enumerate(doc["bands"]):
            if not (lo <= band["min"] <= band["max"] <= hi):
                errors.append(f"{label}: bands[{i}] must sit inside the scale with min <= max")
        if "no_gaps" in doc and not lo <= doc["no_gaps"] <= hi:
            errors.append(f"{label}: no_gaps must sit inside the scale")
        for type_id in doc.get("applies_to") or ():
            if type_id not in types:
                errors.append(f"{label}: applies_to {type_id!r} is not a concept type")

    if "catalog" in c.documents:
        label = c.rel("catalog")
        for type_id in (c.documents["catalog"].get("index") or {}).get("include") or ():
            if type_id not in types:
                errors.append(f"{label}: index.include {type_id!r} is not a concept type")

    if "publishing" in c.documents:
        title = ((c.documents["publishing"].get("issues") or {}).get("title")) or "{kind}"
        if "{kind}" not in title:
            errors.append(f"{c.rel('publishing')}: issues.title must contain {{kind}}")

    return errors


def _check_sections(
    sections: Iterable[Any],
    label: str,
    refs: set[str],
    methods: set[str] | None,
    *,
    parent: str,
    level: int = 2,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for section in section_dicts(sections):
        heading = section["heading"]
        where = f"{label}: {'#' * level} {heading}"
        if heading in seen:
            errors.append(f"{where}: heading is listed twice under {parent or 'the document'}")
        seen.add(heading)
        owner = section.get("owner", "author")
        if owner == "placeholder" and not section.get("placeholder"):
            errors.append(f"{where}: owner placeholder needs placeholder text")
        if owner == "enricher" and not section.get("enrich"):
            errors.append(f"{where}: owner enricher needs an enrich block")
        if section.get("enrich") and owner != "enricher":
            errors.append(f"{where}: an enrich block needs owner: enricher")
        enrich = section.get("enrich") or {}
        if enrich:
            if methods is not None and enrich["method"] not in methods:
                errors.append(
                    f"{where}: enrich.method {enrich['method']!r} is not an engine method "
                    f"({', '.join(sorted(methods)) or 'none'})"
                )
            if enrich.get("lookup") and enrich["lookup"] not in refs:
                errors.append(f"{where}: enrich.lookup {enrich['lookup']!r} is not a reference contract")
        errors.extend(
            _check_sections(
                section.get("subsections") or (),
                label,
                refs,
                methods,
                parent=heading,
                level=level + 1,
            )
        )
    return errors


# ----------------------------------------------------------------------- requirements


def check_requirements(contracts: TargetContracts, required: Mapping[str, Iterable[str]]) -> None:
    """``required`` maps contract kind -> the agents that need it. Missing kinds refuse the run."""
    missing = [
        f"{kind} (needed by {', '.join(sorted(set(agents)))})"
        for kind, agents in sorted(required.items())
        if kind not in contracts.declared
    ]
    if missing:
        raise ContractError(
            f"{INDEX_REL} does not declare contract(s) this pipeline requires: " + "; ".join(missing)
        )


def reject_target_agents(workspace: Path) -> None:
    """Targets ship contracts only. Agent or skill definitions in a target are refused."""
    for rel in ("agents", f"{CONTRACTS_DIR}/agents", f"{CONTRACTS_DIR}/skills"):
        if (workspace / rel).exists():
            raise WorkspaceError(
                f"target ships {rel}/: targets define contracts only; agents and skills belong "
                "to the engine (pick or order them with pipelines in contracts/target.yaml)"
            )
