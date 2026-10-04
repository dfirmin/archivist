"""Target checkout, three-state scaffold, and trusted onboarding publication."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from archivist.errors import WorkspaceError
from archivist.targets import Target, resolve_target

ONBOARDING_BRANCH = "chore/archivist-onboarding"
PUBLISHER_ENV = "ARCHIVIST_PUBLISHER"
_BASE_BRANCH = "main"
# Pipeline commits (publisher scaffold + conductor push). Keep in sync with
# docker/entrypoint.sh defaults.
ENGINE_GIT_NAME = "Archivist"
ENGINE_GIT_EMAIL = "archivist@noreply.local"
# OKF bundle layout, engine-owned. Concept IDs are paths under knowledge/.
KNOWLEDGE_DIR = "knowledge"
INBOX_DIR = "references/inbox/documents"
PROCESSED_DIR = "references/processed/documents"
_SCAFFOLD_DIRS = (KNOWLEDGE_DIR, INBOX_DIR, PROCESSED_DIR)
# The minimum a target needs. Every other contract is optional and added by the target.
_ROOT_FILES = (
    "README.md",
    "AGENTS.md",
    "index.md",
    "log.md",
    "okf/PROFILE.md",
    "contracts/target.yaml",
)


class ScaffoldState(str, Enum):
    EMPTY = "empty"
    SCAFFOLDED = "scaffolded"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    state: ScaffoldState
    written: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrepareResult:
    target: Target
    workspace: Path
    action: str
    scaffold: ScaffoldResult
    commit_sha: str | None = None
    pull_request_url: str | None = None


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )


def bundle_template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "bundle-template"


def _run(
    runner: CommandRunner,
    args: list[str],
    *,
    cwd: Path | None = None,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = runner.run(args, cwd=cwd)
    if result.returncode != 0 and not allow_failure:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise WorkspaceError(f"{' '.join(args[:3])}: {detail}")
    return result


def _present_files(workspace: Path) -> tuple[str, ...]:
    if not workspace.exists():
        return ()
    return tuple(
        path.relative_to(workspace).as_posix()
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    )


def detect_scaffold_state(workspace: Path, target: Target) -> ScaffoldState:
    files = _present_files(workspace)
    if not files:
        return ScaffoldState.EMPTY
    required_files = all((workspace / relative).is_file() for relative in _ROOT_FILES)
    required_dirs = all(
        (workspace / relative).is_dir()
        for relative in _SCAFFOLD_DIRS
    )
    if required_files and required_dirs:
        return ScaffoldState.SCAFFOLDED
    return ScaffoldState.REFUSE


def scaffold_workspace(
    workspace: Path,
    target: Target,
    *,
    template_root: Path | None = None,
) -> ScaffoldResult:
    """Seed an empty workspace without overwriting existing content."""
    state = detect_scaffold_state(workspace, target)
    if state is ScaffoldState.REFUSE:
        top_level = sorted({path.split("/", 1)[0] for path in _present_files(workspace)})
        raise WorkspaceError(
            "target repo is non-empty but does not have the expected scaffold; "
            f"found: {', '.join(top_level)}"
        )
    root = (template_root or bundle_template_root()).resolve()
    written: list[str] = []
    skipped: list[str] = []
    workspace.mkdir(parents=True, exist_ok=True)

    for relative in _SCAFFOLD_DIRS:
        directory = workspace / relative
        directory.mkdir(parents=True, exist_ok=True)
        placeholder = directory / ".gitkeep"
        if placeholder.exists():
            skipped.append(placeholder.relative_to(workspace).as_posix())
        else:
            placeholder.write_text("", encoding="utf-8")
            written.append(placeholder.relative_to(workspace).as_posix())

    for relative in _ROOT_FILES:
        source = root / relative
        if not source.is_file():
            raise WorkspaceError(f"bundle template is missing {relative}")
        destination = workspace / relative
        if destination.exists():
            skipped.append(relative)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        text = text.replace("{{slug}}", target.slug).replace("{{name}}", target.name)
        destination.write_text(text, encoding="utf-8")
        written.append(relative)

    return ScaffoldResult(
        state=ScaffoldState.SCAFFOLDED,
        written=tuple(written),
        skipped=tuple(skipped),
    )


def _publisher_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return env.get(PUBLISHER_ENV) == "1"


def _remote_exists(target: Target, runner: CommandRunner) -> bool:
    result = _run(
        runner,
        ["gh", "repo", "view", target.github_slug],
        allow_failure=True,
    )
    return result.returncode == 0


def force_clone(
    target: Target,
    workspace: Path,
    runner: CommandRunner,
) -> None:
    """Discard any existing checkout and clone the target remote fresh."""
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, ["gh", "repo", "clone", target.github_slug, str(workspace)])


def _ensure_checkout(
    target: Target,
    workspace: Path,
    runner: CommandRunner,
) -> str:
    if not _remote_exists(target, runner):
        _run(
            runner,
            [
                "gh",
                "repo",
                "create",
                target.github_slug,
                "--private",
                "--description",
                target.description,
            ],
        )
    force_clone(target, workspace, runner)
    return "cloned"


def _remote_branch_exists(
    workspace: Path,
    branch: str,
    runner: CommandRunner,
) -> bool:
    result = _run(
        runner,
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        cwd=workspace,
        allow_failure=True,
    )
    return result.returncode == 0


def _checkout_existing_scaffold(
    workspace: Path,
    target: Target,
    runner: CommandRunner,
) -> bool:
    if not _remote_branch_exists(workspace, ONBOARDING_BRANCH, runner):
        return False
    _run(runner, ["git", "checkout", "-B", ONBOARDING_BRANCH, f"origin/{ONBOARDING_BRANCH}"], cwd=workspace)
    return detect_scaffold_state(workspace, target) is ScaffoldState.SCAFFOLDED


def _has_head(workspace: Path, runner: CommandRunner) -> bool:
    result = _run(
        runner,
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=workspace,
        allow_failure=True,
    )
    return result.returncode == 0


def _prepare_base_branch(workspace: Path, runner: CommandRunner) -> None:
    if _has_head(workspace, runner):
        if _remote_branch_exists(workspace, _BASE_BRANCH, runner):
            _run(runner, ["git", "checkout", _BASE_BRANCH], cwd=workspace)
            _run(runner, ["git", "pull", "--ff-only", "origin", _BASE_BRANCH], cwd=workspace)
        return
    _run(runner, ["git", "checkout", "--orphan", _BASE_BRANCH], cwd=workspace)
    _run(runner, ["git", "config", "user.name", ENGINE_GIT_NAME], cwd=workspace)
    _run(
        runner,
        ["git", "config", "user.email", ENGINE_GIT_EMAIL],
        cwd=workspace,
    )
    _run(
        runner,
        ["git", "commit", "--allow-empty", "-m", "chore: initialize knowledge bundle"],
        cwd=workspace,
    )
    _run(runner, ["git", "push", "-u", "origin", _BASE_BRANCH], cwd=workspace)


def _publish_scaffold(
    workspace: Path,
    target: Target,
    runner: CommandRunner,
) -> tuple[str, str]:
    _prepare_base_branch(workspace, runner)
    _run(runner, ["git", "checkout", "-B", ONBOARDING_BRANCH, _BASE_BRANCH], cwd=workspace)
    _run(runner, ["git", "config", "user.name", ENGINE_GIT_NAME], cwd=workspace)
    _run(
        runner,
        ["git", "config", "user.email", ENGINE_GIT_EMAIL],
        cwd=workspace,
    )
    _run(runner, ["git", "add", "-A"], cwd=workspace)
    _run(
        runner,
        ["git", "commit", "-m", f"chore({target.slug}): seed archivist scaffold"],
        cwd=workspace,
    )
    _run(
        runner,
        ["git", "push", "-u", "origin", ONBOARDING_BRANCH, "--force-with-lease"],
        cwd=workspace,
    )
    sha = _run(runner, ["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    create = _run(
        runner,
        [
            "gh",
            "pr",
            "create",
            "--repo",
            target.github_slug,
            "--head",
            ONBOARDING_BRANCH,
            "--base",
            _BASE_BRANCH,
            "--title",
            f"Onboarding: scaffold {target.name}",
            "--body",
            (
                "Seeds the OKF bundle (knowledge/, inbox, processed archive, root navigation) "
                "and a minimal contracts/target.yaml for the target to fill in."
            ),
        ],
        allow_failure=True,
    )
    if create.returncode == 0:
        return sha, create.stdout.strip()
    existing = _run(
        runner,
        [
            "gh",
            "pr",
            "view",
            ONBOARDING_BRANCH,
            "--repo",
            target.github_slug,
            "--json",
            "url",
            "--jq",
            ".url",
        ],
    )
    return sha, existing.stdout.strip()


def prepare_target(
    *,
    target_slug: str,
    workspace: Path,
    registry_path: Path | None = None,
    local: bool = False,
    publish: bool = True,
    runner: CommandRunner | None = None,
    environ: dict[str, str] | None = None,
) -> PrepareResult:
    """Resolve, checkout, scaffold, and optionally publish one registered target."""
    target = resolve_target(target_slug, registry_path)
    workspace = workspace.resolve()
    command_runner = runner or SubprocessRunner()

    if local:
        scaffold = scaffold_workspace(workspace, target)
        return PrepareResult(target, workspace, "local", scaffold)
    if not _publisher_enabled(environ):
        raise WorkspaceError(
            "remote target preparation is restricted to the credentialed publisher container"
        )

    action = _ensure_checkout(target, workspace, command_runner)
    if _checkout_existing_scaffold(workspace, target, command_runner):
        return PrepareResult(
            target,
            workspace,
            "onboarding-branch-exists",
            ScaffoldResult(ScaffoldState.SCAFFOLDED),
        )

    _prepare_base_branch(workspace, command_runner)
    state = detect_scaffold_state(workspace, target)
    if state is ScaffoldState.REFUSE:
        raise WorkspaceError(
            "target repo is non-empty but does not have the expected archivist scaffold"
        )
    scaffold = scaffold_workspace(workspace, target)
    if not publish or not scaffold.written:
        return PrepareResult(target, workspace, action, scaffold)

    sha, pr_url = _publish_scaffold(workspace, target, command_runner)
    return PrepareResult(target, workspace, "published", scaffold, sha, pr_url)
