"""Engine skills: ``skills/<name>/SKILL.md``, one concept each.

A skill is reference material an agent preloads (``skills:`` in its frontmatter) or loads on
demand by description. Skills carry no model. Targets cannot add or override skills: domain
knowledge reaches agents through contracts, which the ``target-contracts`` skill teaches
them to read.

At run time the skills are copied into ``<workspace>/.claude/skills/`` where Claude Code
discovers them.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archivist.errors import DefinitionError
from archivist.frontmatter import check_identity, split_frontmatter

SKILL_FILE = "SKILL.md"


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    path: Path
    description: str
    body: str
    frontmatter: dict[str, Any]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def engine_skills_root() -> Path:
    return repo_root() / "skills"


def parse_skill(skill_dir: Path) -> Skill:
    """Parse ``<skill_dir>/SKILL.md``; the directory name must equal ``name:``."""
    path = skill_dir / SKILL_FILE
    if not path.is_file():
        raise DefinitionError(f"missing {SKILL_FILE}: {path}")
    try:
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except DefinitionError as exc:
        raise DefinitionError(f"{path}: {exc}") from exc
    name, description = check_identity(frontmatter, expected_name=skill_dir.name, label=str(path))
    if "model" in frontmatter or "hooks" in frontmatter:
        raise DefinitionError(f"{path}: a skill carries no model and no hooks")
    if not body.strip():
        raise DefinitionError(f"{path}: the body is the skill and may not be empty")
    return Skill(name, skill_dir, description, body.strip(), frontmatter)


def load_skills(root: Path | None = None) -> dict[str, Skill]:
    root = root or engine_skills_root()
    if not root.is_dir():
        raise DefinitionError(f"engine skills not found: {root}")
    return {
        item.name: parse_skill(item)
        for item in sorted(root.iterdir(), key=lambda p: p.name)
        if item.is_dir()
    }


def reset_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def install_skills(skills: dict[str, Skill], dest: Path) -> None:
    """Copy every engine skill into ``dest`` (real copies: a run cannot edit the engine)."""
    reset_path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name, skill in skills.items():
        shutil.copytree(skill.path, dest / name, symlinks=False)
