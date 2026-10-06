"""Inbox drops and the repo setup the scaffold applies (ADR 0007).

``bundle-template/.github/archivist/inbox.py`` runs in a target, so it is loaded by path and run
against a local fake of the GitHub API. The ruleset is checked through a fake ``gh`` runner.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from archivist.repo_settings import RULESET_NAME, apply_repo_settings, ruleset_body
from archivist.targets import Target, TargetConfigError, load_targets
from archivist.workspace import scaffold_workspace

TEMPLATE = Path(__file__).resolve().parents[1] / "bundle-template"
TARGET = Target("kb", "Test KB", "d", "https://github.com/o/r", "docs", "active", False)


def _load_inbox():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("inbox", TEMPLATE / ".github/archivist/inbox.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["inbox"] = module  # dataclasses look their module up while it loads
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.dont_write_bytecode = previous
    return module


inbox = _load_inbox()
EXT, MAX_KB = inbox.DEFAULT_EXTENSIONS, inbox.DEFAULT_MAX_KB
WRITER = {"author_association": "COLLABORATOR", "user": {"login": "sme"}}


def added(name: str) -> dict:
    return {"filename": name, "status": "added"}


# --- the decision ----------------------------------------------------------------------------

def test_a_drop_of_new_documents_merges() -> None:
    files = [added("sources/inbox/a.md"), added("sources/inbox/b.txt")]
    assert inbox.decide(WRITER, files, EXT, MAX_KB, {"sources/inbox/a.md": 10}).action == "merge"


def test_anything_outside_the_inbox_is_left_for_review() -> None:
    for files in ([added("contracts/intake.yaml")],
                  [added("sources/inbox/a.md"), {"filename": "knowledge/x.md", "status": "modified"}]):
        assert inbox.decide(WRITER, files, EXT, MAX_KB).action == "skip"
    assert inbox.decide({**WRITER, "draft": True}, [added("sources/inbox/a.md")], EXT, MAX_KB).action == "skip"


@pytest.mark.parametrize("pull, item, sizes, reason", [
    (WRITER, {"filename": "sources/inbox/a.md", "status": "modified"}, {}, "not added"),
    (WRITER, {"filename": "sources/inbox/a.md", "status": "removed"}, {}, "not added"),
    (WRITER, added("sources/inbox/run.sh"), {}, "extension"),
    (WRITER, added("sources/inbox/deep/a.md"), {}, "subfolder"),
    (WRITER, added("sources/inbox/.hidden.md"), {}, "subfolder"),
    (WRITER, added("sources/inbox/big.md"), {"sources/inbox/big.md": (MAX_KB + 1) * 1024}, "limit"),
    ({"author_association": "NONE", "user": {"login": "stranger"}}, added("sources/inbox/a.md"), {}, "write access"),
])
def test_a_bad_drop_fails_with_the_reason(pull, item, sizes, reason) -> None:  # type: ignore[no-untyped-def]
    decision = inbox.decide(pull, [item], EXT, MAX_KB, sizes)
    assert decision.action == "fail" and reason in decision.reasons[0]


def test_settings_come_from_repository_variables() -> None:
    assert inbox.settings({}) == (EXT, MAX_KB)
    assert inbox.settings({"ARCHIVIST_INBOX_EXTENSIONS": "md, VTT", "ARCHIVIST_INBOX_MAX_KB": "64"}) == ((".md", ".vtt"), 64)


# --- against a fake GitHub API ---------------------------------------------------------------

class FakeGitHub:
    def __init__(self, files: list[dict], association: str = "OWNER") -> None:
        self.requests: list[tuple[str, str, bytes]] = []
        self.comments: list[dict] = []
        pull = {"number": 7, "draft": False, "author_association": association, "user": {"login": "sme"},
                "head": {"sha": "abc123", "ref": "drop-1", "repo": {"full_name": "o/r"}}}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append((self.command, self.path, body))
                if self.path == "/repos/o/r/pulls/7":
                    payload = pull
                elif self.path.startswith("/repos/o/r/pulls/7/files"):
                    payload = files if "page=1" in self.path else []
                elif self.path.startswith("/repos/o/r/issues/7/comments") and self.command == "GET":
                    payload = outer.comments
                elif self.path.startswith("/repos/o/r/contents/"):
                    payload = {"size": 2048}
                else:
                    payload = {}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_PUT = do_DELETE = do_POST = do_PATCH = _serve

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def env(self, tmp_path: Path) -> dict[str, str]:
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 7}}), encoding="utf-8")
        return {"GITHUB_EVENT_PATH": str(event), "GITHUB_API_URL": self.url, "GITHUB_TOKEN": "t",
                "GITHUB_REPOSITORY": "o/r"}

    def methods(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.requests]


@pytest.fixture
def github():  # type: ignore[no-untyped-def]
    servers: list[FakeGitHub] = []

    def start(*args, **kwargs):  # type: ignore[no-untyped-def]
        servers.append(FakeGitHub(*args, **kwargs))
        return servers[-1]

    yield start
    for server in servers:
        server.server.shutdown()
        server.server.server_close()


def test_a_drop_is_merged_at_the_checked_commit_and_its_branch_deleted(tmp_path: Path, github) -> None:  # type: ignore[no-untyped-def]
    fake = github([added("sources/inbox/notes.md")])
    assert inbox.main([], fake.env(tmp_path)) == 0
    (merge,) = [body for m, p, body in fake.requests if (m, p) == ("PUT", "/repos/o/r/pulls/7/merge")]
    assert json.loads(merge)["sha"] == "abc123" and json.loads(merge)["merge_method"] == "squash"
    assert ("DELETE", "/repos/o/r/git/refs/heads/drop-1") in fake.methods()


def test_a_contract_change_is_not_touched(tmp_path: Path, github) -> None:  # type: ignore[no-untyped-def]
    fake = github([{"filename": "contracts/intake.yaml", "status": "modified"}])
    assert inbox.main([], fake.env(tmp_path)) == 0
    assert all(m == "GET" for m, _ in fake.methods())


def test_a_bad_drop_fails_and_merges_nothing(tmp_path: Path, github) -> None:  # type: ignore[no-untyped-def]
    fake = github([added("sources/inbox/tool.exe")])
    assert inbox.main([], fake.env(tmp_path)) == 1
    assert not any(p.endswith("/merge") or m == "DELETE" for m, p in fake.methods())
    (posted,) = [b for m, p, b in fake.requests if (m, p) == ("POST", "/repos/o/r/issues/7/comments")]
    assert "tool.exe" in json.loads(posted)["body"]

    fake.comments = [{"id": 5, "body": json.loads(posted)["body"]}]  # a second push edits it
    assert inbox.main([], fake.env(tmp_path)) == 1
    assert ("PATCH", "/repos/o/r/issues/comments/5") in fake.methods()


def test_the_workflow_never_runs_the_pull_requests_code() -> None:
    workflow = yaml.safe_load((TEMPLATE / ".github/workflows/inbox.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on") or workflow.get(True)  # PyYAML reads `on:` as True
    assert set(triggers) == {"pull_request_target"}  # the default branch's rules, not the PR's
    (checkout,) = [s for s in workflow["jobs"]["inbox"]["steps"] if s.get("uses", "").startswith("actions/checkout")]
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"


# --- the scaffold seeds the repo files -------------------------------------------------------

def test_scaffold_seeds_codeowners_with_the_inbox_unowned(tmp_path: Path) -> None:
    workspace = tmp_path / "kb"
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0", owners=("@acme/kb-owners",))
    assert {".github/CODEOWNERS", ".github/workflows/inbox.yml", ".github/archivist/inbox.py"} <= set(result.written)
    lines = [line for line in (workspace / ".github/CODEOWNERS").read_text().splitlines()
             if line and not line.startswith("#")]
    assert lines == ["* @acme/kb-owners", "/sources/inbox/"]  # last match wins: the inbox has no owner

    (workspace / ".github/CODEOWNERS").write_text("* @someone-else\n", encoding="utf-8")
    assert scaffold_workspace(workspace, TARGET, engine="v0.1.0").written == ()  # never overwritten


def test_registered_owners_must_be_handles(tmp_path: Path) -> None:
    registry = tmp_path / "targets.yaml"
    entry = "{slug: kb, name: KB, description: d, target_repo: 'https://github.com/o/r', type: docs, status: active"
    registry.write_text(f"targets:\n  - {entry}, owners: ['@acme/kb', '@dee']}}\n", encoding="utf-8")
    assert load_targets(registry)[0].owners == ("@acme/kb", "@dee")
    registry.write_text(f"targets:\n  - {entry}, owners: [dee]}}\n", encoding="utf-8")
    with pytest.raises(TargetConfigError):
        load_targets(registry)


# --- the repo settings -----------------------------------------------------------------------

class GhRunner:
    def __init__(self, existing: str = "", refuse: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.existing, self.refuse = existing, refuse

    def run(self, args, *, cwd=None):  # type: ignore[no-untyped-def]
        self.calls.append(list(args))
        if "--input" in args:
            if self.refuse:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 403: Resource not accessible")
            body = json.loads(Path(args[args.index("--input") + 1]).read_text())
            assert body == ruleset_body()
            return subprocess.CompletedProcess(args, 0, "{}", "")
        if args[2].endswith("/rulesets"):
            return subprocess.CompletedProcess(args, 0, self.existing, "")
        return subprocess.CompletedProcess(args, 0, "true", "")


def test_the_ruleset_is_created_then_replaced_by_name() -> None:
    created = GhRunner()
    ruleset, actions = apply_repo_settings(TARGET, created)
    assert ruleset.applied and actions.applied
    assert any(c[2:5] == ["repos/o/r/rulesets", "-X", "POST"] for c in created.calls)

    replaced = GhRunner(existing="42")
    assert apply_repo_settings(TARGET, replaced)[0].applied
    assert any(c[2:5] == ["repos/o/r/rulesets/42", "-X", "PUT"] for c in replaced.calls)
    assert ruleset_body()["name"] == RULESET_NAME


def test_a_refused_setting_is_reported_not_raised() -> None:
    ruleset, _ = apply_repo_settings(TARGET, GhRunner(refuse=True))
    assert not ruleset.applied and "403" in ruleset.detail and ruleset.line().startswith("TODO")


def test_the_ruleset_requires_code_owner_review_and_no_approval_count() -> None:
    (rule,) = [r for r in ruleset_body()["rules"] if r["type"] == "pull_request"]
    # Approvals would block inbox drops; code owner review blocks everything CODEOWNERS owns.
    assert rule["parameters"]["required_approving_review_count"] == 0
    assert rule["parameters"]["require_code_owner_review"] is True
