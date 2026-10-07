"""``archivist check-concept``: the deterministic check an agent runs after writing frontmatter.

Agents write concept frontmatter by hand. A live run showed why that needs a check: a messy
source's email subject (``FW: RE: meal limit - FINAL``) went into ``sources`` unquoted, and the
colons made the whole frontmatter invalid YAML, which broke every later stage. Whether YAML
parses, whether ``type`` names a real concept type and whether the fields match the contract are
structural facts, not judgement, so a command answers them and the agent fixes what it reports.

It also holds the line ADR 0005 draws around quarantine: a quarantined draft lives under
``quarantine/`` with ``status: quarantined`` and says why, and nothing quarantined is accepted
under ``knowledge/``. A draft reaches ``knowledge/`` only by ``archivist requeue`` and a new
authoring run, so the stages after the author are never skipped by moving a file.

And it checks the body has every heading its structure requires (ADR 0010): live runs on both
harnesses showed authors dropping a required heading in a third to two thirds of view overviews,
where the structure says to stub it. Which headings must exist is the structure's, read as
**document-structure** §3 states it: required author sections and placeholder sections, at their
level; never an optional section or anything under it, never an enricher section or a heading
whose only children are enricher sections. Whether a section has content is judgement and stays
with the gap fleet (``missing_section``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from archivist.contracts import (
    ENGINE_FIELDS,
    EXTENSION_PREFIX,
    INDEX_REL,
    OKF_FIELDS,
    PLACEMENT_FIELD,
    QUARANTINE_FIELD,
    STRUCTURE_FIELD,
    TargetContracts,
    load_contracts,
)
from archivist.errors import ContractError

_DELIM = "---"
QUARANTINE_DIR = "quarantine"
QUARANTINED = "quarantined"
PLACEMENT_OUTCOMES = ("new", "update")


@dataclass(slots=True)
class ConceptReport:
    path: Path
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _frontmatter(text: str) -> tuple[str | None, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _DELIM:
        return None, "the file does not start with a `---` frontmatter block"
    for index in range(1, len(lines)):
        if lines[index].strip() == _DELIM:
            return "\n".join(lines[1:index]), None
    return None, "the frontmatter block is never closed with `---`"


def _find_contracts(concept: Path) -> TargetContracts:
    for candidate in [concept.parent, *concept.parents]:
        if (candidate / INDEX_REL).is_file():
            return load_contracts(candidate)
    raise ContractError(f"{INDEX_REL} not found above {concept}")


def _required_headings(sections: Any, level: int = 2) -> list[tuple[int, str]]:
    """``(level, heading)`` for every heading the author must write, in structure order."""
    out: list[tuple[int, str]] = []
    for section in sections or ():
        if isinstance(section, str):
            out.append((level, section))
            continue
        if not isinstance(section, dict) or section.get("required") is False:
            continue
        owner = section.get("owner", "author")
        children = section.get("subsections") or []
        enricher_only = bool(children) and all(
            isinstance(c, dict) and c.get("owner") == "enricher" for c in children
        )
        if owner == "enricher" or enricher_only:
            continue
        out.append((level, str(section["heading"])))
        out.extend(_required_headings(children, level + 1))
    return out


def _headings(body: str) -> set[tuple[int, str]]:
    found: set[tuple[int, str]] = set()
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            marks = len(line) - len(line.lstrip("#"))
            if marks and line[marks:marks + 1] == " ":
                found.add((marks, line[marks:].strip().rstrip("#").strip()))
    return found


def _check_headings(text: str, structure: dict[str, Any], report: ConceptReport) -> None:
    body = text.split(_DELIM, 2)[2] if text.count(_DELIM) >= 2 else ""
    present = _headings(body)
    for level, heading in _required_headings(structure.get("sections")):
        if (level, heading) not in present:
            report.problems.append(
                f"required heading `{'#' * level} {heading}` is missing (structure "
                f"{structure.get('id')}): write it per document-structure §3, as a stub "
                "`*[Awaiting source material.]*` when no source supports it"
            )


def check_concept(path: Path, *, frontmatter_only: bool = False) -> ConceptReport:
    path = path.resolve()
    report = ConceptReport(path)
    if not path.is_file():
        report.problems.append("file not found")
        return report
    raw, problem = _frontmatter(path.read_text(encoding="utf-8"))
    if problem:
        report.problems.append(problem)
        return report
    try:
        data: Any = yaml.safe_load(raw or "")
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (frontmatter line {mark.line + 1})" if mark is not None else ""
        report.problems.append(
            f"frontmatter is not valid YAML{where}: {getattr(exc, 'problem', exc)}. "
            "Quote any value that contains `: `, `#`, or starts with a special character, "
            'e.g. title: "FW: RE: meal limit"'
        )
        return report
    if not isinstance(data, dict):
        report.problems.append("frontmatter must be a YAML mapping")
        return report

    contracts = _find_contracts(path)
    okf_type = data.get("type")
    if not okf_type and data.get("status") == QUARANTINED:
        # A stub for a document whose class names no concept type (an extract class, ADR 0006).
        _check_location(path, contracts.workspace, data, report)
        _check_sources(data, contracts, report)
        return report
    if not okf_type:
        report.problems.append("`type` is missing (OKF requires it)")
        return report
    type_id = contracts.concept_type_id(str(okf_type))
    if type_id is None:
        known = sorted(spec["type"] for spec in contracts.concept_types().values())
        report.problems.append(f"`type: {okf_type}` is not a concept type in the contracts ({', '.join(known)})")
        return report
    spec = contracts.concept_types()[type_id]
    declared = spec.get("fields") or {}
    quarantined = _check_location(path, contracts.workspace, data, report)

    structure = data.get(STRUCTURE_FIELD)
    allowed = list(spec.get("structures") or ())
    if spec.get("authored") and allowed:
        if structure is None and not quarantined:
            report.problems.append(f"`{STRUCTURE_FIELD}` is missing; record the structure chosen ({', '.join(allowed)})")
        elif structure is not None and structure not in allowed:
            report.problems.append(f"`{STRUCTURE_FIELD}: {structure}` is not one of {type_id}'s structures ({', '.join(allowed)})")

    if not quarantined:  # a quarantined draft may lack exactly the value that quarantined it
        for name, field_spec in declared.items():
            if field_spec.get("required") and data.get(name) in (None, "", []):
                report.problems.append(f"required field `{name}` is missing or empty")
    _check_placement(data.get(PLACEMENT_FIELD), report)
    for name in data:
        if name in OKF_FIELDS or name in ENGINE_FIELDS or name in declared:
            continue
        if name.startswith(EXTENSION_PREFIX):
            report.problems.append(f"`{name}` is not declared on concept type {type_id}")
        else:
            report.problems.append(f"`{name}` is neither an OKF field nor an okfx_ field")

    _check_sources(data, contracts, report)
    if not quarantined and not frontmatter_only and spec.get("authored") and structure in allowed:
        structure_doc = contracts.structures().get(str(structure))
        if isinstance(structure_doc, dict):
            _check_headings(path.read_text(encoding="utf-8"), structure_doc, report)
    return report


def _check_sources(data: dict[str, Any], contracts: TargetContracts, report: ConceptReport) -> None:
    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            report.problems.append("`sources` must be a list")
        else:
            for i, entry in enumerate(sources):
                if not isinstance(entry, dict) or not entry.get("resource"):
                    report.problems.append(f"`sources[{i}]` needs a `resource`")
                elif not (contracts.workspace / str(entry["resource"])).is_file():
                    report.problems.append(f"`sources[{i}].resource` does not exist: {entry['resource']}")


def _check_location(path: Path, workspace: Path, data: dict[str, Any], report: ConceptReport) -> bool:
    """Whether the file is a quarantined draft; records a problem when status and place disagree."""
    try:
        top = path.relative_to(workspace.resolve()).parts[0]
    except (ValueError, IndexError):
        top = ""
    quarantined = data.get("status") == QUARANTINED
    if quarantined and top != QUARANTINE_DIR:
        report.problems.append(
            f"`status: {QUARANTINED}` belongs under {QUARANTINE_DIR}/ only. A quarantined draft "
            f"reaches {top or 'this place'}/ by `archivist requeue {QUARANTINE_DIR}/<file>.md` "
            "and a new authoring run, never by moving it"
        )
    if top == QUARANTINE_DIR and not quarantined:
        report.problems.append(f"a file under {QUARANTINE_DIR}/ needs `status: {QUARANTINED}`")
    note = data.get(QUARANTINE_FIELD)
    if quarantined:
        if not isinstance(note, dict):
            report.problems.append(f"`{QUARANTINE_FIELD}` is missing; give `reason` and `needs`")
        else:
            for key in ("reason", "needs"):
                if not str(note.get(key) or "").strip():
                    report.problems.append(f"`{QUARANTINE_FIELD}.{key}` is missing or empty")
            candidates = note.get("candidates")
            if candidates is not None and not isinstance(candidates, list):
                report.problems.append(f"`{QUARANTINE_FIELD}.candidates` must be a list of concept paths")
    elif note is not None:
        report.problems.append(f"`{QUARANTINE_FIELD}` belongs only on a quarantined draft")
    return quarantined


def _check_placement(placement: Any, report: ConceptReport) -> None:
    if placement is None:
        return
    if not isinstance(placement, dict):
        report.problems.append(f"`{PLACEMENT_FIELD}` must be a mapping with `outcome` (and `matched` on update)")
        return
    outcome = placement.get("outcome")
    if outcome not in PLACEMENT_OUTCOMES:
        report.problems.append(f"`{PLACEMENT_FIELD}.outcome: {outcome}` is not one of {', '.join(PLACEMENT_OUTCOMES)}")
    elif outcome == "update" and not str(placement.get("matched") or "").strip():
        report.problems.append(f"`{PLACEMENT_FIELD}.matched` names the identity value an update matched")
