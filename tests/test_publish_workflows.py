"""The publishing workflows the scaffold ships, and the script they run.

The script (``bundle-template/.github/archivist/publish.py``) runs in a target, not in the engine,
so it is loaded by path here and exercised against a local fake of each destination's API.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from archivist.targets import Target
from archivist.workspace import ScaffoldState, detect_scaffold_state, scaffold_workspace

TEMPLATE = Path(__file__).resolve().parents[1] / "bundle-template"
ARCHIVIST_DIR = ".github/archivist"
WORKFLOWS = ("publish-databricks", "publish-confluence", "publish-sharepoint")
TARGET = Target("kb", "Test KB", "d", "https://github.com/example-org/kb", "docs", "active", False)


def _load_publish():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("publish", TEMPLATE / ARCHIVIST_DIR / "publish.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ in the template
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.dont_write_bytecode = previous
    return module


publish = _load_publish()


def _manifest() -> dict:
    return yaml.safe_load((TEMPLATE / ARCHIVIST_DIR / "secrets.yaml").read_text(encoding="utf-8"))


# --- the scaffold seeds them -----------------------------------------------------------------

def test_scaffold_seeds_the_publishing_files_once(tmp_path: Path) -> None:
    workspace = tmp_path / "kb"
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    seeded = {f".github/workflows/{name}.yml" for name in WORKFLOWS} | {
        f"{ARCHIVIST_DIR}/publish.py", f"{ARCHIVIST_DIR}/secrets.yaml", f"{ARCHIVIST_DIR}/SECRETS.md",
        "quarantine/README.md"}
    assert seeded <= set(result.written)

    edited = workspace / ".github/workflows/publish-databricks.yml"
    edited.write_text("# the target's own runner\n", encoding="utf-8")
    again = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    assert again.written == ()  # idempotent
    assert edited.read_text(encoding="utf-8") == "# the target's own runner\n"  # never overwritten


def test_an_existing_target_gets_the_files_without_losing_its_scaffold_state(tmp_path: Path) -> None:
    workspace = tmp_path / "kb"
    scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    for path in sorted((workspace / ".github").rglob("*"), reverse=True):  # a target scaffolded earlier
        path.unlink() if path.is_file() else path.rmdir()
    (workspace / ".github").rmdir()
    assert detect_scaffold_state(workspace, TARGET) is ScaffoldState.SCAFFOLDED
    result = scaffold_workspace(workspace, TARGET, engine="v0.1.0")
    assert {f".github/workflows/{name}.yml" for name in WORKFLOWS} <= set(result.written)


def test_templates_carry_no_scaffold_placeholders() -> None:
    """The scaffold substitutes {{slug}}, {{name}} and {{engine}}; GitHub expressions must survive."""
    for path in (TEMPLATE / ".github").rglob("*"):
        if path.is_file():
            assert not re.search(r"\{\{(slug|name|engine)\}\}", path.read_text(encoding="utf-8")), path


# --- the workflows, the manifest and the script agree ----------------------------------------

def _workflow(name: str) -> tuple[dict, str]:
    text = (TEMPLATE / ".github/workflows" / f"{name}.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text), text


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflows_run_only_when_started_by_hand(name: str) -> None:
    data, _ = _workflow(name)
    triggers = data.get("on", data.get(True))  # YAML reads a bare `on` as true
    assert set(triggers) == {"workflow_dispatch"}


@pytest.mark.parametrize("name", WORKFLOWS)
def test_each_workflow_passes_exactly_the_names_the_manifest_lists(name: str) -> None:
    destination = name.removeprefix("publish-")
    _, text = _workflow(name)
    entry = _manifest()["workflows"][name]
    assert entry["file"] == f".github/workflows/{name}.yml"

    secrets = {s["name"] for s in entry["secrets"]}
    variables = {v["name"] for v in entry["variables"]}
    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) == secrets == set(publish.SECRETS[destination])
    assert set(re.findall(r"vars\.([A-Z0-9_]+)", text)) == variables
    assert variables == set(publish.SETTINGS[destination]) | set(publish.OPTIONAL_SETTINGS[destination])
    required = {v["name"] for v in entry["variables"] if v["required"]}
    assert required == set(publish.SETTINGS[destination])

    checklist = (TEMPLATE / ARCHIVIST_DIR / "SECRETS.md").read_text(encoding="utf-8")
    for needed in secrets | variables:
        assert f"`{needed}`" in checklist, f"SECRETS.md does not mention {needed}"


# --- the script ------------------------------------------------------------------------------

def test_check_names_every_missing_secret_and_setting(capsys: pytest.CaptureFixture[str]) -> None:
    assert publish.main(["sharepoint", "--check"], env={"SHAREPOINT_CLIENT_ID": "  "}) == 2
    err = capsys.readouterr().err
    for name in ("SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET", "SHAREPOINT_SITE_URL"):
        assert name in err

    # a dry run needs the settings but never the secrets
    assert publish.main(["sharepoint", "--check", "--dry-run"], env={}) == 2
    assert "SHAREPOINT_TENANT_ID" not in capsys.readouterr().err
    assert publish.main(["databricks", "--check", "--dry-run"], env={"DATABRICKS_PATH": "/Volumes/c/s/v"}) == 0


def test_dry_run_lists_files_and_sends_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _knowledge(tmp_path)
    env = {"DATABRICKS_PATH": "/Volumes/c/s/v/kb", "DATABRICKS_HOST": "http://127.0.0.1:9"}  # nothing listens
    assert publish.main(["databricks", "--dry-run", "--source", str(root)], env=env) == 0
    out = capsys.readouterr().out
    assert "a.md -> /Volumes/c/s/v/kb/a.md" in out and "sub/b.md -> /Volumes/c/s/v/kb/sub/b.md" in out


def test_an_empty_knowledge_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / ".gitkeep").write_text("")
    env = {"DATABRICKS_PATH": "/Volumes/c/s/v"}
    assert publish.main(["databricks", "--dry-run", "--source", str(tmp_path / "knowledge")], env=env) == 1


def test_confluence_titles_stay_unique(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir()
    (root / "x" / "a.md").write_text("---\ntitle: Policy\n---\nOne\n", encoding="utf-8")
    (root / "y" / "a.md").write_text("---\ntitle: \"Policy\"\n---\nTwo\n", encoding="utf-8")
    (root / "c.md").write_text("# From heading\n\ntext\n", encoding="utf-8")
    pytest.importorskip("markdown")
    titles = sorted(title for _, title, _ in publish.confluence_pages(root, sorted(root.rglob("*.md"))))
    assert titles == ["From heading", "Policy (x/a)", "Policy (y/a)"]


# --- the script against a local fake of each API ----------------------------------------------

def _knowledge(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / "sub").mkdir(parents=True)
    (root / ".gitkeep").write_text("")
    (root / "a.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n| k | v |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    (root / "sub" / "b.md").write_text("---\ntitle: Beta\n---\nBeta body\n", encoding="utf-8")
    return root


class FakeApi:
    """A local HTTP server that records requests and answers from ``respond``."""

    def __init__(self, respond) -> None:  # type: ignore[no-untyped-def]
        self.requests: list[tuple[str, str, dict[str, str], bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                status, payload = respond(self.command, self.path, body)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_PUT = do_POST = _serve

            def log_message(self, *args: object) -> None:  # keep test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def seen(self, method: str, path: str) -> list[tuple[str, str, dict[str, str], bytes]]:
        return [r for r in self.requests if r[0] == method and r[1] == path]


@pytest.fixture
def api():  # type: ignore[no-untyped-def]
    servers: list[FakeApi] = []

    def start(respond):  # type: ignore[no-untyped-def]
        servers.append(FakeApi(respond))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def test_databricks_volume_gets_directories_then_files(tmp_path: Path, api) -> None:  # type: ignore[no-untyped-def]
    fake = api(lambda method, path, body: (200, {}))
    env = {"DATABRICKS_HOST": fake.url, "DATABRICKS_TOKEN": "tok", "DATABRICKS_PATH": "/Volumes/c/s/v/kb/"}
    assert publish.main(["databricks", "--source", str(_knowledge(tmp_path))], env=env) == 0

    for folder in ("/Volumes/c/s/v/kb", "/Volumes/c/s/v/kb/sub"):
        assert fake.seen("PUT", f"/api/2.0/fs/directories{folder}")
    (uploaded,) = fake.seen("PUT", "/api/2.0/fs/files/Volumes/c/s/v/kb/sub/b.md?overwrite=true")
    assert uploaded[3] == (tmp_path / "knowledge/sub/b.md").read_bytes()
    assert uploaded[2]["Authorization"] == "Bearer tok"
    assert not any(r[1].endswith(".gitkeep") or ".gitkeep" in r[1] for r in fake.requests)


def test_databricks_workspace_folder_uses_the_workspace_api(tmp_path: Path, api) -> None:  # type: ignore[no-untyped-def]
    fake = api(lambda method, path, body: (200, {}))
    env = {"DATABRICKS_HOST": fake.url, "DATABRICKS_TOKEN": "tok", "DATABRICKS_PATH": "/Workspace/Shared/kb"}
    assert publish.main(["databricks", "--source", str(_knowledge(tmp_path))], env=env) == 0

    made = [json.loads(r[3])["path"] for r in fake.seen("POST", "/api/2.0/workspace/mkdirs")]
    assert made == ["/Shared/kb", "/Shared/kb/sub"]
    imported = {json.loads(r[3])["path"]: json.loads(r[3]) for r in fake.seen("POST", "/api/2.0/workspace/import")}
    assert set(imported) == {"/Shared/kb/a.md", "/Shared/kb/sub/b.md"}
    assert imported["/Shared/kb/sub/b.md"]["overwrite"] is True


def test_one_failed_file_fails_the_run_but_not_the_others(tmp_path: Path, api, capsys) -> None:  # type: ignore[no-untyped-def]
    def respond(method: str, path: str, body: bytes) -> tuple[int, dict]:
        return (403, {"error": "denied"}) if path.startswith("/api/2.0/fs/files/Volumes/c/s/v/a.md") else (200, {})

    fake = api(respond)
    env = {"DATABRICKS_HOST": fake.url, "DATABRICKS_TOKEN": "tok", "DATABRICKS_PATH": "/Volumes/c/s/v"}
    assert publish.main(["databricks", "--source", str(_knowledge(tmp_path))], env=env) == 1
    assert fake.seen("PUT", "/api/2.0/fs/files/Volumes/c/s/v/sub/b.md?overwrite=true")  # still written
    captured = capsys.readouterr()
    assert "FAILED a.md" in captured.err and "tok" not in captured.out + captured.err


def test_confluence_creates_under_the_parent_and_updates_by_title(tmp_path: Path, api) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("markdown")

    def respond(method: str, path: str, body: bytes) -> tuple[int, dict]:
        if method == "GET" and "title=Beta" in path:
            return 200, {"results": [{"id": "42", "version": {"number": 3}, "body": {"storage": {"value": "old"}}}]}
        if method == "GET":
            return 200, {"results": []}
        return 200, {}

    fake = api(respond)
    env = {"CONFLUENCE_URL": fake.url + "/", "CONFLUENCE_TOKEN": "tok", "CONFLUENCE_SPACE_KEY": "KB",
           "CONFLUENCE_PARENT_PAGE_ID": "7"}
    assert publish.main(["confluence", "--source", str(_knowledge(tmp_path))], env=env) == 0

    (created,) = fake.seen("POST", "/rest/api/content")
    page = json.loads(created[3])
    assert (page["title"], page["space"], page["ancestors"]) == ("Alpha", {"key": "KB"}, [{"id": "7"}])
    assert "<table>" in page["body"]["storage"]["value"] and created[2]["Authorization"] == "Bearer tok"
    (updated,) = fake.seen("PUT", "/rest/api/content/42")
    assert json.loads(updated[3])["version"] == {"number": 4}
    assert "ancestors" not in json.loads(updated[3])  # an existing page is not moved


def test_confluence_skips_a_page_whose_content_has_not_changed(tmp_path: Path, api) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("markdown")
    root = _knowledge(tmp_path)
    same = publish.storage_html("Beta body\n", "knowledge/sub/b.md")

    def respond(method: str, path: str, body: bytes) -> tuple[int, dict]:
        found = {"id": "42", "version": {"number": 3}, "body": {"storage": {"value": same}}}
        return 200, {"results": [found] if method == "GET" and "title=Beta" in path else []}

    fake = api(respond)
    env = {"CONFLUENCE_URL": fake.url, "CONFLUENCE_TOKEN": "tok", "CONFLUENCE_SPACE_KEY": "KB"}
    assert publish.main(["confluence", "--source", str(root)], env=env) == 0
    assert not fake.seen("PUT", "/rest/api/content/42")


def test_sharepoint_signs_in_finds_the_library_and_uploads(tmp_path: Path, api) -> None:  # type: ignore[no-untyped-def]
    def respond(method: str, path: str, body: bytes) -> tuple[int, dict]:
        if path == "/tenant-1/oauth2/v2.0/token":
            return 200, {"access_token": "graph-token"}
        if path == "/v1.0/sites/contoso.sharepoint.com:/sites/Knowledge":
            return 200, {"id": "site-1"}
        if path == "/v1.0/sites/site-1/drives":
            return 200, {"value": [{"id": "d0", "name": "Other"}, {"id": "d1", "name": "Documents"}]}
        return 200, {}

    fake = api(respond)
    env = {"SHAREPOINT_TENANT_ID": "tenant-1", "SHAREPOINT_CLIENT_ID": "cid", "SHAREPOINT_CLIENT_SECRET": "shh",
           "SHAREPOINT_SITE_URL": "https://contoso.sharepoint.com/sites/Knowledge",
           "SHAREPOINT_FOLDER": "kb", "SHAREPOINT_LOGIN_URL": fake.url, "SHAREPOINT_GRAPH_URL": fake.url}
    assert publish.main(["sharepoint", "--source", str(_knowledge(tmp_path))], env=env) == 0

    (token,) = fake.seen("POST", "/tenant-1/oauth2/v2.0/token")
    assert b"grant_type=client_credentials" in token[3] and b"client_id=cid" in token[3]
    (uploaded,) = fake.seen("PUT", "/v1.0/drives/d1/root:/kb/sub/b.md:/content?@microsoft.graph.conflictBehavior=replace")
    assert uploaded[2]["Authorization"] == "Bearer graph-token"
    assert uploaded[3] == (tmp_path / "knowledge/sub/b.md").read_bytes()


def test_sharepoint_names_the_libraries_it_found(tmp_path: Path, api, capsys) -> None:  # type: ignore[no-untyped-def]
    def respond(method: str, path: str, body: bytes) -> tuple[int, dict]:
        if path.endswith("/token"):
            return 200, {"access_token": "t"}
        if path.startswith("/v1.0/sites/contoso"):
            return 200, {"id": "s"}
        return 200, {"value": [{"id": "d0", "name": "Shared Documents"}]}

    fake = api(respond)
    env = {"SHAREPOINT_TENANT_ID": "t", "SHAREPOINT_CLIENT_ID": "c", "SHAREPOINT_CLIENT_SECRET": "s",
           "SHAREPOINT_SITE_URL": "https://contoso.sharepoint.com/sites/K", "SHAREPOINT_LIBRARY": "Docs",
           "SHAREPOINT_LOGIN_URL": fake.url, "SHAREPOINT_GRAPH_URL": fake.url}
    assert publish.main(["sharepoint", "--source", str(_knowledge(tmp_path))], env=env) == 1
    assert "Shared Documents" in capsys.readouterr().err
