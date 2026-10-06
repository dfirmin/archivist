#!/usr/bin/env python3
"""Merge inbox drops: pull requests that only add documents to sources/inbox/ (ADR 0007).

Run by .github/workflows/inbox.yml on every pull request into the default branch. Standard
library only. It reads the pull request through the GitHub REST API and never checks out or
runs anything from the pull request's branch.

A pull request is an **inbox drop** when every file in it is added (not modified, renamed or
removed) directly under ``sources/inbox/``. A drop is merged when:

- its author has write access (owner, member or collaborator), so a fork cannot feed the engine;
- every file has an allowed extension (``ARCHIVIST_INBOX_EXTENSIONS``, default ``.md,.txt``);
- no file is larger than ``ARCHIVIST_INBOX_MAX_KB`` (default 1024).

A drop that breaks a rule fails the check and says why in a comment on the pull request (one
comment, updated on each push), so the person who opened it sees what to fix. Anything that is not a drop (a contract change, a mix of inbox and other files, an engine
run's pull request) passes the check untouched and waits for a code owner's review as usual.

    python3 .github/archivist/inbox.py              # in the workflow
    python3 .github/archivist/inbox.py --dry-run    # decide and report, merge nothing
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

INBOX = "sources/inbox/"
DEFAULT_EXTENSIONS = (".md", ".txt")
DEFAULT_MAX_KB = 1024
WRITERS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass
class Decision:
    """``merge`` a valid drop, ``fail`` an invalid one, ``skip`` anything that is not a drop."""

    action: str
    reasons: list[str] = field(default_factory=list)


def settings(environ: dict[str, str]) -> tuple[tuple[str, ...], int]:
    raw = environ.get("ARCHIVIST_INBOX_EXTENSIONS", "").strip()
    extensions = tuple(
        (item if item.startswith(".") else f".{item}").lower()
        for item in (part.strip() for part in raw.split(","))
        if item
    ) or DEFAULT_EXTENSIONS
    try:
        max_kb = int(environ.get("ARCHIVIST_INBOX_MAX_KB", "").strip() or DEFAULT_MAX_KB)
    except ValueError:
        max_kb = DEFAULT_MAX_KB
    return extensions, max_kb


def decide(pull: dict, files: list[dict], extensions: tuple[str, ...], max_kb: int,
           sizes: dict[str, int] | None = None) -> Decision:
    """Pure decision over the pull request and its files (``sizes``: bytes per added path)."""
    if pull.get("draft"):
        return Decision("skip", ["draft pull request"])
    if not files:
        return Decision("skip", ["no files changed"])
    if any(not item["filename"].startswith(INBOX) for item in files):
        return Decision("skip", ["changes files outside sources/inbox/; needs a code owner's review"])

    reasons: list[str] = []
    if pull.get("author_association") not in WRITERS:
        reasons.append(
            f"opened by {pull.get('user', {}).get('login', 'someone')} without write access to this "
            "repository; a maintainer must review it"
        )
    for item in files:
        name = item["filename"]
        rest = name[len(INBOX):]
        if item.get("status") != "added":
            reasons.append(f"{name}: {item.get('status')}, not added; the inbox only takes new documents")
            continue
        if "/" in rest or rest.startswith("."):
            reasons.append(f"{name}: put documents directly in sources/inbox/, not in a subfolder or hidden file")
            continue
        if not name.lower().endswith(extensions):
            reasons.append(f"{name}: extension not accepted (allowed: {', '.join(extensions)})")
        size = (sizes or {}).get(name)
        if size is not None and size > max_kb * 1024:
            reasons.append(f"{name}: {size // 1024} KB is over the {max_kb} KB limit")
    return Decision("fail", reasons) if reasons else Decision("merge")


class GitHub:
    def __init__(self, api: str, token: str, repo: str) -> None:
        self.api, self.token, self.repo = api.rstrip("/"), token, repo

    def call(self, method: str, path: str, body: dict | None = None) -> object:
        request = urllib.request.Request(
            f"{self.api}/repos/{self.repo}/{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def files(self, number: int) -> list[dict]:
        found: list[dict] = []
        for page in range(1, 31):  # GitHub lists at most 3000 files
            batch = self.call("GET", f"pulls/{number}/files?per_page=100&page={page}")
            found += batch  # type: ignore[operator]
            if len(batch) < 100:  # type: ignore[arg-type]
                break
        return found

    def size(self, path: str, ref: str) -> int:
        quoted = urllib.parse.quote(path)
        meta = self.call("GET", f"contents/{quoted}?ref={urllib.parse.quote(ref)}")
        return int(meta["size"])  # type: ignore[index]


MARKER = "<!-- archivist-inbox -->"


def comment(github: GitHub, number: int, text: str) -> None:
    """One comment per pull request, replaced on each run; best effort."""
    body = f"{MARKER}\n{text}"
    try:
        existing = github.call("GET", f"issues/{number}/comments?per_page=100")
        mine = [c for c in existing if MARKER in (c.get("body") or "")]  # type: ignore[union-attr]
        if mine:
            github.call("PATCH", f"issues/comments/{mine[0]['id']}", {"body": body})
        else:
            github.call("POST", f"issues/{number}/comments", {"body": body})
    except urllib.error.HTTPError:
        pass  # the check result still says it failed


def summary(text: str, environ: dict[str, str]) -> None:
    print(text)
    target = environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def main(argv: list[str], environ: dict[str, str]) -> int:
    dry_run = "--dry-run" in argv
    event = json.load(open(environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    number = int(event["pull_request"]["number"])
    github = GitHub(environ.get("GITHUB_API_URL", "https://api.github.com"),
                    environ["GITHUB_TOKEN"], environ["GITHUB_REPOSITORY"])
    pull = github.call("GET", f"pulls/{number}")
    files = github.files(number)
    extensions, max_kb = settings(environ)
    head = pull["head"]["sha"]  # type: ignore[index]
    sizes = {
        item["filename"]: github.size(item["filename"], head)
        for item in files
        if item["filename"].startswith(INBOX) and item.get("status") == "added"
    } if all(item["filename"].startswith(INBOX) for item in files) else {}
    decision = decide(pull, files, extensions, max_kb, sizes)  # type: ignore[arg-type]

    if decision.action == "skip":
        summary(f"Not an inbox drop ({decision.reasons[0]}). Left for review.", environ)
        return 0
    if decision.action == "fail":
        text = ("**Inbox drop not merged.** Fix these and push again, or ask a code owner to review it:\n\n"
                + "\n".join(f"- {reason}" for reason in decision.reasons))
        summary(text, environ)
        if not dry_run:
            comment(github, number, text)
        return 1
    names = ", ".join(item["filename"][len(INBOX):] for item in files)
    if dry_run:
        summary(f"Inbox drop would be merged (dry run): {names}", environ)
        return 0
    try:
        github.call("PUT", f"pulls/{number}/merge", {
            "merge_method": "squash",
            "sha": head,  # merge exactly what was checked
            "commit_title": f"inbox: add {names}"[:250],
        })
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        summary(f"Inbox drop passed the checks but GitHub refused the merge ({err.code}): {detail}", environ)
        return 1
    branch = pull["head"]  # type: ignore[index]
    if branch.get("repo") and branch["repo"].get("full_name") == environ["GITHUB_REPOSITORY"]:
        try:
            github.call("DELETE", f"git/refs/heads/{urllib.parse.quote(branch['ref'])}")
        except urllib.error.HTTPError:
            pass  # a protected or already-deleted branch is not a failure
    summary(f"Inbox drop merged: {names}", environ)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], dict(os.environ)))
