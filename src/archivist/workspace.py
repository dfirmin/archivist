"""Target checkout, three-state scaffold, and trusted onboarding publication."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import yaml

from archivist.engines import scaffold_pin
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
# What makes a repo an archivist target (scaffold detection). Starter contracts and examples
# are seeded too, but a target may replace or delete them.
_ROOT_FILES = (
    "README.md",
    "AGENTS.md",
    "index.md",
    "log.md",
    "okf/PROFILE.md",
    "contracts/target.yaml",
)


_INDEX = "contracts/target.yaml"
# Generic, valid starter contracts: the full pipeline runs on a fresh scaffold.
_STARTER_FILES = (
    "contracts/concept-types.yaml",
    "contracts/structures/article.yaml",
    "contracts/intake.yaml",
    "contracts/gap-kinds.yaml",
    "contracts/scoring.yaml",
)
_EXAMPLES_DIR = "examples"


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


def engine_examples_root() -> Path:
    return Path(__file__).resolve().parents[2] / "examples"


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
    engine: str | None = None,
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
    pin = scaffold_pin(engine)
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

    def render(relative: str) -> str:
        source = root / relative
        if not source.is_file():
            raise WorkspaceError(f"bundle template is missing {relative}")
        return (
            source.read_text(encoding="utf-8")
            .replace("{{slug}}", target.slug)
            .replace("{{name}}", target.name)
            .replace("{{engine}}", pin)
        )

    def write(relative: str, text: str, *, replace: bool = False) -> None:
        destination = workspace / relative
        if destination.exists() and not replace:
            skipped.append(relative)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        written.append(relative)

    # The contract index decides whether the starter contracts are seeded: on a new target, or
    # on an index that still declares nothing (an untouched or pre-starter scaffold). An index
    # that declares contracts is the target's own and is only given an engine pin if it lacks one.
    index = workspace / _INDEX
    seed_starters = not index.exists() or _declares_nothing(index)
    for relative in _ROOT_FILES:
        if relative == _INDEX:
            continue
        write(relative, render(relative))
    if seed_starters:
        for relative in _STARTER_FILES:
            write(relative, render(relative))
        write(_INDEX, render(_INDEX), replace=True)
    elif _add_missing_pin(index, pin):
        written.append(f"{_INDEX} (engine pin added)")
    else:
        skipped.append(_INDEX)

    # Reference copies of the engine's example targets (documentation; agents never read them).
    examples = engine_examples_root()
    write(f"{_EXAMPLES_DIR}/README.md", render("examples-README.md"))
    for example in sorted(p for p in examples.iterdir() if (p / "contracts").is_dir()):
        for source in sorted((example / "contracts").rglob("*")):
            if source.is_file():
                relative = f"{_EXAMPLES_DIR}/{example.name}/{source.relative_to(example).as_posix()}"
                write(relative, source.read_text(encoding="utf-8"))

    return ScaffoldResult(
        state=ScaffoldState.SCAFFOLDED,
        written=tuple(written),
        skipped=tuple(skipped),
    )


def _declares_nothing(index: Path) -> bool:
    """True for an index with no contracts and no reference data (safe to replace)."""
    try:
        data = yaml.safe_load(index.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and not data.get("contracts") and not data.get("reference")


def _add_missing_pin(index: Path, pin: str) -> bool:
    """Insert ``engine: <pin>`` after ``slug:`` in an index that has no pin. True if changed."""
    text = index.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or data.get("engine"):
        return False
    lines = text.splitlines(keepends=True)
    at = next((i + 1 for i, line in enumerate(lines) if line.startswith("slug:")), len(lines))
    lines.insert(at, f"engine: {pin}\n")
    index.write_text("".join(lines), encoding="utf-8")
    return True


def _publisher_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return env.get(PUBLISHER_ENV) == "1"


def _gh_api(runner: CommandRunner, path: str, *fields: str, method: str | None = None,
            typed: tuple[str, ...] = (), jq: str | None = None,
            allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    """One GitHub REST call through ``gh api``.

    REST rather than ``gh repo``/``gh pr`` subcommands: those use GraphQL, which some tokens,
    proxies and GitHub Enterprise setups do not allow, while REST works wherever ``gh`` does.
    """
    args = ["gh", "api", path]
    if method:
        args += ["-X", method]
    for field_ in fields:
        args += ["-f", field_]  # string field
    for field_ in typed:
        args += ["-F", field_]  # typed field: true/false/numbers
    if jq:
        args += ["--jq", jq]
    return _run(runner, args, allow_failure=allow_failure)


def _remote_exists(target: Target, runner: CommandRunner) -> bool:
    return _gh_api(runner, f"repos/{target.github_slug}", allow_failure=True).returncode == 0


def _clone_url(target: Target) -> str:
    return target.target_repo if target.target_repo.endswith(".git") else f"{target.target_repo}.git"


def force_clone(
    target: Target,
    workspace: Path,
    runner: CommandRunner,
) -> None:
    """Discard any existing checkout and clone the target remote fresh (plain git)."""
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, ["git", "clone", _clone_url(target), str(workspace)])


def _ensure_checkout(
    target: Target,
    workspace: Path,
    runner: CommandRunner,
) -> str:
    if not _remote_exists(target, runner):
        owner, name = target.github_slug.split("/")
        login = _gh_api(runner, "user", jq=".login").stdout.strip()
        path = "user/repos" if owner == login else f"orgs/{owner}/repos"
        _gh_api(runner, path, f"name={name}", f"description={target.description}",
                typed=("private=true",), method="POST")
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


def _open_onboarding_pr(target: Target, runner: CommandRunner) -> str | None:
    """The open onboarding PR's URL. A merged or closed one means onboarding may run again."""
    owner = target.github_slug.split("/")[0]
    url = _gh_api(
        runner,
        f"repos/{target.github_slug}/pulls?head={owner}:{ONBOARDING_BRANCH}&state=open",
        jq=".[0].html_url // empty",
        allow_failure=True,
    ).stdout.strip()
    return url or None


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
        # --force: the branch is engine-owned; a leftover from a merged onboarding is replaced.
        ["git", "push", "-u", "origin", ONBOARDING_BRANCH, "--force"],
        cwd=workspace,
    )
    sha = _run(runner, ["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    created = _gh_api(
        runner,
        f"repos/{target.github_slug}/pulls",
        f"title=Onboarding: scaffold {target.name}",
        f"head={ONBOARDING_BRANCH}",
        f"base={_BASE_BRANCH}",
        (
            "body=Seeds the OKF bundle (knowledge/, inbox, processed archive, root navigation) "
            "and a minimal contracts/target.yaml for the target to fill in."
        ),
        method="POST",
        jq=".html_url",
    )
    return sha, created.stdout.strip()


def prepare_target(
    *,
    target_slug: str,
    workspace: Path,
    registry_path: Path | None = None,
    local: bool = False,
    publish: bool = True,
    runner: CommandRunner | None = None,
    environ: dict[str, str] | None = None,
    engine: str | None = None,
) -> PrepareResult:
    """Resolve, checkout, scaffold, and optionally publish one registered target."""
    target = resolve_target(target_slug, registry_path)
    workspace = workspace.resolve()
    command_runner = runner or SubprocessRunner()

    if local:
        scaffold = scaffold_workspace(workspace, target, engine=engine)
        return PrepareResult(target, workspace, "local", scaffold)
    if not _publisher_enabled(environ):
        raise WorkspaceError(
            "remote target preparation is restricted to the credentialed publisher container"
        )

    action = _ensure_checkout(target, workspace, command_runner)
    open_pr = _open_onboarding_pr(target, command_runner)
    if open_pr:
        return PrepareResult(
            target,
            workspace,
            "onboarding-pr-open",
            ScaffoldResult(ScaffoldState.SCAFFOLDED),
            pull_request_url=open_pr,
        )

    _prepare_base_branch(workspace, command_runner)
    state = detect_scaffold_state(workspace, target)
    if state is ScaffoldState.REFUSE:
        raise WorkspaceError(
            "target repo is non-empty but does not have the expected archivist scaffold"
        )
    scaffold = scaffold_workspace(workspace, target, engine=engine)
    if not publish or not scaffold.written:
        return PrepareResult(target, workspace, action, scaffold)

    sha, pr_url = _publish_scaffold(workspace, target, command_runner)
    return PrepareResult(target, workspace, "published", scaffold, sha, pr_url)
