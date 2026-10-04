"""``archivist check-concept``: the deterministic check an agent runs after writing frontmatter.

Agents write concept frontmatter by hand. A live run showed why that needs a check: a messy
source's email subject (``FW: RE: meal limit - FINAL``) went into ``sources`` unquoted, and the
colons made the whole frontmatter invalid YAML, which broke every later stage. Whether YAML
parses, whether ``type`` names a real concept type and whether the fields match the contract are
structural facts, not judgement, so a command answers them and the agent fixes what it reports.
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
    STRUCTURE_FIELD,
    TargetContracts,
    load_contracts,
)
from archivist.errors import ContractError

_DELIM = "---"


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


def check_concept(path: Path) -> ConceptReport:
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

    structure = data.get(STRUCTURE_FIELD)
    allowed = list(spec.get("structures") or ())
    if spec.get("authored") and allowed:
        if structure is None:
            report.problems.append(f"`{STRUCTURE_FIELD}` is missing; record the structure chosen ({', '.join(allowed)})")
        elif structure not in allowed:
            report.problems.append(f"`{STRUCTURE_FIELD}: {structure}` is not one of {type_id}'s structures ({', '.join(allowed)})")

    for name, field_spec in declared.items():
        if field_spec.get("required") and data.get(name) in (None, "", []):
            report.problems.append(f"required field `{name}` is missing or empty")
    for name in data:
        if name in OKF_FIELDS or name in ENGINE_FIELDS or name in declared:
            continue
        if name.startswith(EXTENSION_PREFIX):
            report.problems.append(f"`{name}` is not declared on concept type {type_id}")
        else:
            report.problems.append(f"`{name}` is neither an OKF field nor an okfx_ field")

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
    return report
