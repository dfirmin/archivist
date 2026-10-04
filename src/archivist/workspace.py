"""Target checkout, three-state scaffold, and trusted onboarding publication."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import yaml

from archivist.engines import (
    DEFAULT_ENGINE_REPO,
    ENGINE_REPO_ENV,
    PINNED_ENV,
    ensure_engine,
    read_pin,
    running_commit,
    running_version,
    scaffold_pin,
)
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
INBOX_DIR = "sources/inbox"
PROCESSED_DIR = "sources/processed"
_SCAFFOLD_DIRS = (KNOWLEDGE_DIR, INBOX_DIR, PROCESSED_DIR)
# Layouts earlier engines scaffolded: (old directory, new directory). prepare-target moves
# them, rewrites the paths that cite them, and pins the target to the engine that migrated it.
_LEGACY_DIRS = (
    ("references/inbox/documents", INBOX_DIR),
    ("references/processed/documents", PROCESSED_DIR),
)
_LEGACY_PATHS = (  # longest first
    ("references/inbox/documents/", "sources/inbox/"),
    ("references/processed/documents/", "sources/processed/"),
    ("references/inbox/", "sources/inbox/"),
    ("references/processed/", "sources/processed/"),
    ("`references/`", "`sources/`"),
    # Whole lines the references-era bundle template wrote (README tree, index section).
    ("└── references/       # Source documents concepts cite",
     "└── sources/          # Source documents: inbox/ (waiting) and processed/ (cited)"),
    ("## References\n\n- Raw inputs: `sources/inbox/`\n- Consumed inputs: `sources/processed/`",
     "## Sources\n\n- Waiting to be authored: `sources/inbox/`\n- Authored and cited: `sources/processed/`"),
)
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
    "contracts/structures/how-to.yaml",
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
    legacy = dict((new, old) for old, new in _LEGACY_DIRS)
    required_dirs = all(
        # A directory an earlier layout had under another name counts: scaffolding migrates it.
        (workspace / relative).is_dir() or (relative in legacy and (workspace / legacy[relative]).is_dir())
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
    resolved: list[str] = []

    def pin() -> str:
        """The pin to write, resolved only when something is written with it."""
        if not resolved:
            resolved.append(scaffold_pin(engine))
        return resolved[0]

    current = read_pin(workspace)
    legacy = any((workspace / old).is_dir() for old, _ in _LEGACY_DIRS)  # migration re-pins
    if engine is not None and current and current != engine.strip() and not legacy:
        raise WorkspaceError(
            f"{target.slug} already pins engine {current}; move it with "
            f"`prepare-target --target {target.slug} --upgrade {engine.strip()}`"
        )
    written: list[str] = []
    skipped: list[str] = []
    workspace.mkdir(parents=True, exist_ok=True)
    migrated = _migrate_legacy_layout(workspace, written)

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
        text = source.read_text(encoding="utf-8")
        if "{{engine}}" in text:
            text = text.replace("{{engine}}", pin())
        return text.replace("{{slug}}", target.slug).replace("{{name}}", target.name)

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
    elif migrated and _set_pin(index, pin()):
        written.append(f"{_INDEX} (engine pin set to {pin()}: the layout changed)")
    elif not current and _add_missing_pin(index, pin()):
        written.append(f"{_INDEX} (engine pin added)")
    else:
        skipped.append(_INDEX)

    _refresh_examples(workspace, engine_examples_root().parent, render("examples-README.md"), written, skipped)

    return ScaffoldResult(
        state=ScaffoldState.SCAFFOLDED,
        written=tuple(written),
        skipped=tuple(skipped),
    )


def _refresh_examples(workspace: Path, engine_root: Path, readme: str | None,
                      written: list[str], skipped: list[str]) -> None:
    """Refresh the reference copies of an engine's example targets (agents never read them).

    ``engine_root`` is that engine's source tree: its ``examples/`` are copied, so a target
    always holds the examples of the engine it is pinned to.
    """
    def put(relative: str, text: str) -> None:
        destination = workspace / relative
        if destination.exists() and destination.read_text(encoding="utf-8") == text:
            skipped.append(relative)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        written.append(relative)

    if readme is not None:
        put(f"{_EXAMPLES_DIR}/README.md", readme)
    examples = engine_root / "examples"
    for example in sorted(p for p in examples.iterdir() if (p / "contracts").is_dir()) if examples.is_dir() else ():
        for source in sorted([*(example / "contracts").rglob("*"), *(example / "sources").rglob("*")]):
            if source.is_file():
                put(f"{_EXAMPLES_DIR}/{example.name}/{source.relative_to(example).as_posix()}",
                    source.read_text(encoding="utf-8"))


def _migrate_legacy_layout(workspace: Path, written: list[str]) -> bool:
    """Move an earlier layout's directories to the current one and rewrite paths citing them.

    Mechanical, so deterministic: files move as they are, and every Markdown file at the
    bundle root, in okf/ and under knowledge/ has the old paths replaced (concept ``sources``
    entries, citation lines, index/log links, the root README and AGENTS).
    """
    moved = False
    for old, new in _LEGACY_DIRS:
        source = workspace / old
        if not source.is_dir():
            continue
        target = workspace / new
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.name == ".gitkeep":
                item.unlink()
                continue
            destination = target / item.name
            if destination.exists():
                raise WorkspaceError(f"cannot migrate {old}/{item.name}: {new}/{item.name} already exists")
            item.rename(destination)
            written.append(f"{new}/{item.name} (moved from {old}/)")
        source.rmdir()
        moved = True
    if not moved:
        return False
    legacy_root = workspace / "references"
    for leftover in sorted(legacy_root.rglob("*"), reverse=True) if legacy_root.exists() else ():
        if leftover.is_file() and leftover.name == ".gitkeep":
            leftover.unlink()
        elif leftover.is_dir() and not any(leftover.iterdir()):
            leftover.rmdir()
    if legacy_root.exists() and not any(legacy_root.iterdir()):
        legacy_root.rmdir()
    for path in sorted(
        [*workspace.glob("*.md"), *workspace.glob("okf/*.md"), *workspace.glob("knowledge/**/*.md")]
    ):
        text = path.read_text(encoding="utf-8")
        new_text = text
        for old_path, new_path in _LEGACY_PATHS:
            new_text = new_text.replace(old_path, new_path)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            written.append(f"{path.relative_to(workspace).as_posix()} (paths updated)")
    return True


def _set_pin(index: Path, pin: str) -> bool:
    """Set ``engine:`` to ``pin`` (adding it if absent). True if the file changed."""
    text = index.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("engine:"):
            if line.strip() == f"engine: {pin}":
                return False
            lines[i] = f"engine: {pin}\n"
            index.write_text("".join(lines), encoding="utf-8")
            return True
    return _add_missing_pin(index, pin)


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
    *,
    open_pr: str | None = None,
) -> tuple[str, str, bool]:
    """Commit the scaffold on the onboarding branch and push it; open a PR unless one is open.

    With an open onboarding PR the branch is refreshed (the PR follows it) only when the
    content differs from what the PR already holds. Returns (sha, PR URL, pushed).
    """
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
    if open_pr:
        same = _run(runner, ["git", "diff", "--quiet", f"origin/{ONBOARDING_BRANCH}", "HEAD"],
                    cwd=workspace, allow_failure=True)
        if same.returncode == 0:
            sha = _run(runner, ["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
            return sha, open_pr, False
    _run(
        runner,
        # --force: the branch is engine-owned; a leftover from a merged onboarding is replaced.
        ["git", "push", "-u", "origin", ONBOARDING_BRANCH, "--force"],
        cwd=workspace,
    )
    sha = _run(runner, ["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    if open_pr:
        return sha, open_pr, True
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
    return sha, created.stdout.strip(), True


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

    _prepare_base_branch(workspace, command_runner)
    state = detect_scaffold_state(workspace, target)
    if state is ScaffoldState.REFUSE:
        raise WorkspaceError(
            "target repo is non-empty but does not have the expected archivist scaffold"
        )
    scaffold = scaffold_workspace(workspace, target, engine=engine)
    if not publish or not scaffold.written:
        return PrepareResult(target, workspace, action, scaffold, pull_request_url=open_pr)

    sha, pr_url, changed = _publish_scaffold(workspace, target, command_runner, open_pr=open_pr)
    if open_pr:
        return PrepareResult(target, workspace, "onboarding-pr-updated" if changed else "onboarding-pr-open",
                             scaffold, sha, pr_url)
    return PrepareResult(target, workspace, "published", scaffold, sha, pr_url)


UPGRADE_BRANCH = "archivist/upgrade-engine-{pin}"


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    target: Target
    workspace: Path
    action: str  # "up-to-date", "local", "checked", "published", "pr-updated"
    previous: str | None
    pin: str
    written: tuple[str, ...] = ()
    validation: str = ""
    commit_sha: str | None = None
    pull_request_url: str | None = None


def _engine_source(pin: str, environ: dict[str, str] | None) -> tuple[Path, list[str], list[str]]:
    """The source tree of engine ``pin`` and the command that runs its CLI.

    This engine when the pin names it; otherwise the pinned engine, installed into the cache
    the same way a pinned run installs it. Returns (source tree, CLI command, flags for validate).
    """
    if pin in (running_version(), running_commit()):
        return engine_examples_root().parent, [sys.executable, "-m", "archivist.cli"], ["--engine", "current"]
    bin_dir = ensure_engine(pin, environ=environ)
    return bin_dir.parents[1] / "src", [str(bin_dir / "archivist")], []


def _validate_with(command: list[str], flags: list[str], workspace: Path,
                   environ: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
    """``archivist validate`` on the target, run by the engine the target now pins.

    The default pipeline, plus every pipeline the target defines itself.
    """
    env = dict(environ if environ is not None else os.environ)
    env.pop(PINNED_ENV, None)
    data = yaml.safe_load((workspace / _INDEX).read_text(encoding="utf-8")) or {}
    pipelines = [f"--pipeline={name}" for name in (data.get("pipelines") or {})]
    output: list[str] = []
    for extra in ([], pipelines) if pipelines else ([],):
        result = subprocess.run([*command, "validate", str(workspace), *flags, *extra],
                                capture_output=True, text=True, env=env)
        output.append((result.stdout + result.stderr).strip())
        if result.returncode != 0:
            return subprocess.CompletedProcess(result.args, result.returncode, "\n".join(output), "")
    return subprocess.CompletedProcess(command, 0, "\n".join(output), "")


def upgrade_target(
    *,
    target_slug: str,
    workspace: Path,
    pin: str,
    registry_path: Path | None = None,
    local: bool = False,
    publish: bool = True,
    runner: CommandRunner | None = None,
    environ: dict[str, str] | None = None,
) -> UpgradeResult:
    """Move an existing target to another engine: the pin and the examples, nothing else.

    Contracts, sources, knowledge, index and log are never touched. The target is validated by
    the engine it moves to before anything is committed; a failure leaves the target as it was
    on GitHub and reports what that engine refused.
    """
    target = resolve_target(target_slug, registry_path)
    workspace = workspace.resolve()
    pin = scaffold_pin(pin.strip())
    command_runner = runner or SubprocessRunner()

    if not local:
        if not _publisher_enabled(environ):
            raise WorkspaceError("remote target preparation is restricted to the credentialed publisher container")
        _ensure_checkout(target, workspace, command_runner)
        _prepare_base_branch(workspace, command_runner)
    if detect_scaffold_state(workspace, target) is not ScaffoldState.SCAFFOLDED:
        raise WorkspaceError(
            f"{target.slug} is not an archivist target yet; scaffold it with prepare-target (no --upgrade)"
        )
    previous = read_pin(workspace)
    if previous == pin:
        return UpgradeResult(target, workspace, "up-to-date", previous, pin)

    source, command, flags = _engine_source(pin, environ)
    index = workspace / _INDEX
    original = index.read_text(encoding="utf-8")
    written: list[str] = []
    skipped: list[str] = []
    _set_pin(index, pin)
    written.append(f"{_INDEX} (engine {previous} → {pin})")
    readme_template = source / "bundle-template" / "examples-README.md"
    readme = (readme_template.read_text(encoding="utf-8").replace("{{slug}}", target.slug)
              .replace("{{name}}", target.name).replace("{{engine}}", pin)
              if readme_template.is_file() else None)
    _refresh_examples(workspace, source, readme, written, skipped)

    validation = _validate_with(command, flags, workspace, environ)
    if validation.returncode != 0:
        index.write_text(original, encoding="utf-8")
        raise WorkspaceError(
            f"engine {pin} refuses {target.slug}'s contracts; the pin was not changed:\n{validation.stdout}"
        )
    if local:
        return UpgradeResult(target, workspace, "local", previous, pin, tuple(written), validation.stdout)
    if not publish:
        return UpgradeResult(target, workspace, "checked", previous, pin, tuple(written), validation.stdout)

    branch = UPGRADE_BRANCH.format(pin=pin if pin.startswith("v") else pin[:12])
    for args in (
        ["git", "checkout", "-B", branch, _BASE_BRANCH],
        ["git", "config", "user.name", ENGINE_GIT_NAME],
        ["git", "config", "user.email", ENGINE_GIT_EMAIL],
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"chore({target.slug}): upgrade engine {previous} → {pin}"],
        ["git", "push", "-u", "origin", branch, "--force"],  # engine-owned branch
    ):
        _run(command_runner, args, cwd=workspace)
    sha = _run(command_runner, ["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()

    owner = target.github_slug.split("/")[0]
    existing = _gh_api(command_runner, f"repos/{target.github_slug}/pulls?head={owner}:{branch}&state=open",
                       jq=".[0].html_url // empty", allow_failure=True).stdout.strip()
    if existing:
        return UpgradeResult(target, workspace, "pr-updated", previous, pin, tuple(written),
                             validation.stdout, sha, existing)
    env = environ if environ is not None else os.environ
    repo = (env.get(ENGINE_REPO_ENV, "").strip() or DEFAULT_ENGINE_REPO).removesuffix(".git")
    body = "\n".join([
        f"Moves `{target.slug}` from engine `{previous}` to `{pin}`.",
        "",
        f"- What changed in the engine: {repo}/compare/{previous}...{pin}",
        "- Changed here: the `engine:` line in `contracts/target.yaml` and the reference copies in "
        "`examples/`. Contracts, sources and knowledge are untouched.",
        f"- Validated by engine `{pin}`:",
        "",
        "```",
        validation.stdout,
        "```",
        "",
        "Before merging, a trial run on the new engine (the pin on `main` stays as it is):",
        "",
        "```bash",
        f"archivist run-conductor <checkout> --engine {pin} --skip-publish",
        "```",
    ])
    created = _gh_api(command_runner, f"repos/{target.github_slug}/pulls",
                      f"title=Upgrade engine to {pin}", f"head={branch}", f"base={_BASE_BRANCH}",
                      f"body={body}", method="POST", jq=".html_url")
    return UpgradeResult(target, workspace, "published", previous, pin, tuple(written),
                         validation.stdout, sha, created.stdout.strip())
