"""The GitHub settings the engine applies to a target repo (ADR 0007).

The scaffold ships files; some of what a target needs is a repository setting instead. The
engine owns exactly one thing there: a branch ruleset named ``archivist`` on the default branch
(pull request required, code owner review, no force push, no deletion; admins may bypass). It
is created or replaced on every remote ``prepare-target`` and upgrade, and nothing else in the
repo's settings is touched. Teams that want more add rulesets of their own; GitHub applies the
strictest of all of them.

What cannot be applied (no admin rights, an organization policy) is reported, never fatal: the
scaffold's files are still useful, and the report says what to set by hand.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archivist.targets import Target
    from archivist.workspace import CommandRunner

RULESET_NAME = "archivist"
_ADMIN_ROLE = 5  # GitHub's built-in repository role id for admins


@dataclass(frozen=True, slots=True)
class SettingResult:
    name: str
    applied: bool
    detail: str

    def line(self) -> str:
        return f"{'SET ' if self.applied else 'TODO'}      {self.name}: {self.detail}"


def ruleset_body() -> dict:
    """The ``archivist`` ruleset. Inbox drops pass it because CODEOWNERS leaves sources/inbox/
    unowned: a pull request touching only that path needs no review, so the inbox workflow can
    merge it with the workflow token, and no bypass is needed for it."""
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [
            {"actor_id": _ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "always"},
        ],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "require_code_owner_review": True,
                    "dismiss_stale_reviews_on_push": True,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
    }


def _gh(runner: CommandRunner, args: list[str]) -> tuple[int, str]:
    result = runner.run(["gh", "api", *args])
    return result.returncode, (result.stdout if result.returncode == 0 else (result.stderr or result.stdout)).strip()


def _apply_ruleset(target: Target, runner: CommandRunner) -> SettingResult:
    repo = target.github_slug
    code, listing = _gh(runner, [f"repos/{repo}/rulesets", "--jq",
                                 f'[.[] | select(.name == "{RULESET_NAME}") | .id] | first // empty'])
    if code != 0:
        return SettingResult("ruleset", False, f"could not read rulesets ({listing}); "
                             "add a ruleset on main requiring a pull request and code owner review")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(ruleset_body(), handle)
        body = handle.name
    try:
        if listing:
            code, out = _gh(runner, [f"repos/{repo}/rulesets/{listing}", "-X", "PUT", "--input", body])
            verb = "updated"
        else:
            code, out = _gh(runner, [f"repos/{repo}/rulesets", "-X", "POST", "--input", body])
            verb = "created"
    finally:
        Path(body).unlink(missing_ok=True)
    if code != 0:
        return SettingResult("ruleset", False, f"GitHub refused it ({out}); an admin can create the "
                             f"'{RULESET_NAME}' ruleset by hand: pull request + code owner review on main")
    return SettingResult("ruleset", True, f"'{RULESET_NAME}' {verb} on the default branch")


def _check_actions(target: Target, runner: CommandRunner) -> SettingResult:
    code, out = _gh(runner, [f"repos/{target.github_slug}/actions/permissions", "--jq", ".enabled"])
    if code != 0:
        return SettingResult("actions", False, f"could not read the Actions setting ({out}); "
                             "the inbox and publishing workflows need Actions enabled")
    if out != "true":
        return SettingResult("actions", False, "GitHub Actions is disabled on this repo; enable it "
                             "(Settings > Actions) or inbox drops will not merge")
    return SettingResult("actions", True, "enabled")


def apply_repo_settings(target: Target, runner: CommandRunner) -> tuple[SettingResult, ...]:
    """Apply what the engine owns and report each setting; never raises for a refused setting."""
    return (_apply_ruleset(target, runner), _check_actions(target, runner))


def default_owner(runner: CommandRunner) -> str | None:
    """The person running the scaffold, as a CODEOWNERS handle, when no owners are registered."""
    code, login = _gh(runner, ["user", "--jq", ".login"])
    return f"@{login}" if code == 0 and login else None
