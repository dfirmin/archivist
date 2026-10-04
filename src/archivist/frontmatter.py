"""Shared parsing for the two Markdown definitions the engine loads: skills and agents.

Both are a YAML frontmatter block followed by a Markdown body, and both follow the Claude
Code / Agent Skills naming rules: a lowercase-hyphen ``name`` of at most 64 characters, a
non-empty ``description`` of at most 1024 characters, and neither may contain XML tags.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from archivist.errors import DefinitionError

MAX_NAME = 64
MAX_DESCRIPTION = 1024
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_XML_TAG = re.compile(r"<[^>]+>")
_RESERVED = ("anthropic", "claude")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body). Raises DefinitionError on unparseable YAML."""
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return {}, text
    try:
        loaded = yaml.safe_load(text[4:closing])
    except yaml.YAMLError as exc:
        raise DefinitionError(f"invalid frontmatter: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise DefinitionError("frontmatter must be a mapping")
    return loaded, text[closing + len("\n---\n") :].lstrip("\n")


def split_list(value: Any) -> tuple[str, ...]:
    """Split a tools/skills value on commas and whitespace, keeping ``Bash(a b)`` whole."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    out: list[str] = []
    current: list[str] = []
    depth = 0
    for char in str(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (char == "," or char.isspace()):
            if current:
                out.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        out.append("".join(current))
    return tuple(out)


def check_identity(frontmatter: dict[str, Any], *, expected_name: str, label: str) -> tuple[str, str]:
    """Validate ``name`` and ``description``; return them (description on one line)."""
    name = frontmatter.get("name")
    if not isinstance(name, str) or name.strip() != expected_name:
        raise DefinitionError(f"{label}: name must be {expected_name!r}, got {name!r}")
    if len(expected_name) > MAX_NAME or not _NAME.fullmatch(expected_name):
        raise DefinitionError(
            f"{label}: name must be lowercase letters, numbers and hyphens, "
            f"at most {MAX_NAME} characters"
        )
    if any(word in expected_name for word in _RESERVED):
        raise DefinitionError(f"{label}: name may not contain {' or '.join(_RESERVED)}")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise DefinitionError(f"{label}: description is required")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION:
        raise DefinitionError(f"{label}: description is longer than {MAX_DESCRIPTION} characters")
    if _XML_TAG.search(description):
        raise DefinitionError(f"{label}: description may not contain XML tags")
    return expected_name, description
