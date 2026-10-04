"""Clone a registered target fresh and validate its contracts (publisher container only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from archivist.engine import ResolvedRun, resolve_run
from archivist.errors import WorkspaceError
from archivist.targets import Target, resolve_target
from archivist.workspace import CommandRunner, SubprocessRunner, _publisher_enabled, force_clone


@dataclass(frozen=True, slots=True)
class LoadTargetResult:
    target: Target
    workspace: Path
    run: ResolvedRun


def load_target(
    *,
    target_slug: str,
    workspace: Path,
    registry_path: Path | None = None,
    runner: CommandRunner | None = None,
    environ: dict[str, str] | None = None,
    validate: bool = True,
) -> LoadTargetResult | Target:
    if not _publisher_enabled(environ):
        raise WorkspaceError("load-target is restricted to the credentialed publisher container")
    target = resolve_target(target_slug, registry_path)
    workspace = workspace.resolve()
    force_clone(target, workspace, runner or SubprocessRunner())
    if not validate:
        return target  # the caller validates, possibly on the target's pinned engine
    run = resolve_run(workspace, expected_slug=target.slug)
    return LoadTargetResult(target, workspace, run)
