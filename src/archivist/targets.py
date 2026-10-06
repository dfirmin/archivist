"""The engine's target registry, ``targets.yaml``: which knowledge repos archivist may run on."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from archivist.errors import ArchivistError

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_GITHUB_HOSTS = {"github.com", "github.example.com"}


class TargetConfigError(ArchivistError):
    """The target registry (targets.yaml) is invalid or names an unknown target."""


@dataclass(frozen=True, slots=True)
class Target:
    slug: str
    name: str
    description: str
    target_repo: str
    type: str
    status: str
    auto_trigger: bool
    # A test target that mirrors one of the engine's examples/: its contracts and inbox are
    # that example's, re-copied on onboarding and on every engine upgrade.
    mirrors: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def github_slug(self) -> str:
        parsed = urlparse(self.target_repo)
        path = parsed.path.removesuffix(".git").strip("/")
        if parsed.scheme != "https" or parsed.hostname not in _GITHUB_HOSTS:
            raise TargetConfigError(
                f"target {self.slug!r}: unsupported GitHub URL {self.target_repo!r}"
            )
        if len(path.split("/")) != 2:
            raise TargetConfigError(
                f"target {self.slug!r}: expected owner/repo URL, got {self.target_repo!r}"
            )
        return path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TargetConfigError(f"configuration file not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TargetConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TargetConfigError(f"configuration root must be a mapping: {path}")
    return value


def _required_text(mapping: dict[str, Any], field: str, *, context: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TargetConfigError(f"{context}: {field!r} must be non-empty text")
    return value.strip()


def _validate_slug(slug: str, *, context: str) -> None:
    if not _SLUG.fullmatch(slug):
        raise TargetConfigError(f"{context}: invalid slug {slug!r}")


def _mirrors(raw: dict[str, Any], *, context: str) -> str | None:
    value = raw.get("mirrors")
    if value is None:
        return None
    if not isinstance(value, str) or not _SLUG.fullmatch(value.strip()):
        raise TargetConfigError(f"{context}: 'mirrors' must name an example directory")
    if not (project_root() / "examples" / value.strip() / "contracts").is_dir():
        raise TargetConfigError(f"{context}: 'mirrors' names {value!r}, which is not in examples/")
    return value.strip()


def load_targets(registry_path: Path | None = None) -> tuple[Target, ...]:
    path = (registry_path or project_root() / "targets.yaml").resolve()
    data = _load_mapping(path)
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise TargetConfigError(f"{path}: 'targets' must be a non-empty list")

    seen: set[str] = set()
    targets: list[Target] = []
    for index, raw in enumerate(raw_targets):
        context = f"{path}: targets[{index}]"
        if not isinstance(raw, dict):
            raise TargetConfigError(f"{context} must be a mapping")
        slug = _required_text(raw, "slug", context=context)
        _validate_slug(slug, context=context)
        if slug in seen:
            raise TargetConfigError(f"{path}: duplicate target slug {slug!r}")
        seen.add(slug)

        target = Target(
            slug=slug,
            name=_required_text(raw, "name", context=context),
            description=_required_text(raw, "description", context=context),
            target_repo=_required_text(raw, "target_repo", context=context),
            type=_required_text(raw, "type", context=context),
            status=_required_text(raw, "status", context=context),
            auto_trigger=bool(raw.get("auto_trigger", False)),
            mirrors=_mirrors(raw, context=context),
        )
        if target.status not in {"active", "inactive"}:
            raise TargetConfigError(
                f"target {slug!r}: status must be 'active' or 'inactive'"
            )
        _ = target.github_slug  # validates the URL
        targets.append(target)
    return tuple(targets)


def resolve_target(slug: str, registry_path: Path | None = None) -> Target:
    for target in load_targets(registry_path):
        if target.slug == slug:
            if not target.active:
                raise TargetConfigError(f"target {slug!r} is inactive")
            return target
    raise TargetConfigError(f"unknown target slug {slug!r}")
