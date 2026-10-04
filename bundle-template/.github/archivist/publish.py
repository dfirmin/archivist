#!/usr/bin/env python3
"""Publish this repository's knowledge/ directory to an external destination.

Seeded by `archivist prepare-target` and run by the publish-* workflows in .github/workflows/.
Standard library only; the Confluence destination also needs the `markdown` package
(the workflow installs it).

    publish.py databricks|confluence|sharepoint [--source knowledge] [--check] [--dry-run]

Credentials and settings arrive as environment variables, which the workflows fill from GitHub
secrets, repository variables and workflow inputs. The names each destination needs are listed
in .github/archivist/secrets.yaml and explained in .github/archivist/SECRETS.md. Nothing here
prints a credential.

This copies the current files out; it never deletes anything at the destination, so a concept
removed from knowledge/ stays where it was published until someone removes it there.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

# Per destination: the GitHub secrets, the settings that are required, and the optional settings.
SECRETS = {
    "databricks": ["DATABRICKS_HOST", "DATABRICKS_TOKEN"],
    "confluence": ["CONFLUENCE_URL", "CONFLUENCE_TOKEN"],
    "sharepoint": ["SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET"],
}
SETTINGS = {
    "databricks": ["DATABRICKS_PATH"],
    "confluence": ["CONFLUENCE_SPACE_KEY"],
    "sharepoint": ["SHAREPOINT_SITE_URL"],
}
OPTIONAL_SETTINGS = {
    "databricks": [],
    "confluence": ["CONFLUENCE_PARENT_PAGE_ID"],
    "sharepoint": ["SHAREPOINT_LIBRARY", "SHAREPOINT_FOLDER", "SHAREPOINT_LOGIN_URL", "SHAREPOINT_GRAPH_URL"],
}
SECRETS_DOC = ".github/archivist/SECRETS.md"
RETRY_STATUS = (429, 500, 502, 503, 504)
sleep: Callable[[float], None] = time.sleep  # replaced in tests


class PublishError(Exception):
    """A problem worth reporting as one line."""


# --- checks ---------------------------------------------------------------------------------

def missing(destination: str, env: dict[str, str], *, dry_run: bool) -> tuple[list[str], list[str]]:
    """(secrets, settings) that are unset or blank. A dry run needs no secrets."""
    secrets = [] if dry_run else [n for n in SECRETS[destination] if not env.get(n, "").strip()]
    settings = [n for n in SETTINGS[destination] if not env.get(n, "").strip()]
    return secrets, settings


def check(destination: str, env: dict[str, str], *, dry_run: bool) -> None:
    secrets, settings = missing(destination, env, dry_run=dry_run)
    if not (secrets or settings):
        return
    lines = [f"Cannot publish to {destination}: not set yet."]
    if secrets:
        lines.append(f"  secrets:  {', '.join(secrets)}  (Settings > Secrets and variables > Actions > Secrets)")
    if settings:
        lines.append(f"  settings: {', '.join(settings)}  (a workflow input, or a repository variable of that name)")
    lines.append(f"See {SECRETS_DOC}.")
    raise PublishError("\n".join(lines))


# --- files ----------------------------------------------------------------------------------

def source_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise PublishError(f"{root} is not a directory")
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != ".gitkeep")
    if not files:
        raise PublishError(f"nothing to publish: {root} has no files")
    return files


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# --- http -----------------------------------------------------------------------------------

def request(method: str, url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None,
            timeout: int = 60, attempts: int = 3) -> bytes:
    """One HTTP call with a retry on throttling and server errors. Raises PublishError."""
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            if error.code in RETRY_STATUS and attempt < attempts - 1:
                sleep(float(error.headers.get("Retry-After") or 2 ** attempt))
                continue
            detail = body[:300].decode("utf-8", "replace").strip()
            raise PublishError(f"{method} {url} returned HTTP {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            if attempt < attempts - 1:
                sleep(2 ** attempt)
                continue
            raise PublishError(f"{method} {url} failed: {error.reason}") from None
    raise PublishError(f"{method} {url} failed")  # unreachable


def call_json(method: str, url: str, *, headers: dict[str, str], body: object | None = None) -> object:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    sent = {**headers, "Accept": "application/json"}
    if payload is not None:
        sent["Content-Type"] = "application/json"
    raw = request(method, url, headers=sent, data=payload)
    return json.loads(raw) if raw.strip() else {}


def quote_path(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def with_scheme(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if re.match(r"^https?://", url) else f"https://{url}"


# --- databricks -----------------------------------------------------------------------------

def publish_databricks(root: Path, files: list[Path], env: dict[str, str], dry_run: bool) -> tuple[list[str], list[str]]:
    """Files go to a Unity Catalog volume (Files API) or a workspace folder (Workspace API)."""
    base = env["DATABRICKS_PATH"].strip().rstrip("/")
    if not base.startswith("/"):
        raise PublishError(f"DATABRICKS_PATH must be an absolute path, got {base!r}")
    volume = base.startswith("/Volumes/")
    if volume and len(base.strip("/").split("/")) < 4:
        raise PublishError("a volume path is /Volumes/<catalog>/<schema>/<volume>[/<folder>]")
    if not volume:
        base = re.sub(r"^/Workspace(?=/)", "", base)  # the Workspace API addresses paths without it
    plan = [(path, f"{base}/{relative(path, root)}") for path in files]
    if dry_run:
        return [f"{relative(p, root)} -> {dest}" for p, dest in plan], []

    host = with_scheme(env["DATABRICKS_HOST"])
    auth = {"Authorization": f"Bearer {env['DATABRICKS_TOKEN'].strip()}"}
    folders = sorted({base, *(dest.rsplit("/", 1)[0] for _, dest in plan)})
    for folder in folders:
        if volume:
            request("PUT", f"{host}/api/2.0/fs/directories{quote_path(folder)}", headers=auth, data=b"")
        else:
            call_json("POST", f"{host}/api/2.0/workspace/mkdirs", headers=auth, body={"path": folder})
    done: list[str] = []
    failed: list[str] = []
    for path, dest in plan:
        try:
            content = path.read_bytes()
            if volume:
                request("PUT", f"{host}/api/2.0/fs/files{quote_path(dest)}?overwrite=true",
                        headers={**auth, "Content-Type": "application/octet-stream"}, data=content)
            else:
                call_json("POST", f"{host}/api/2.0/workspace/import", headers=auth, body={
                    "path": dest, "format": "AUTO", "overwrite": True,
                    "content": base64.b64encode(content).decode("ascii"),
                })
            done.append(f"{relative(path, root)} -> {dest}")
        except PublishError as error:
            failed.append(f"{relative(path, root)}: {error}")
    return done, failed


# --- confluence -----------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter block, body) of a Markdown file; the block is empty when there is none."""
    text = text.lstrip("﻿")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.DOTALL)
    return (match.group(1), match.group(2)) if match else ("", text)


def page_title(frontmatter: str, body: str, fallback: str) -> str:
    found = re.search(r"^title:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    if found:
        return found.group(1).strip().strip("\"'") or fallback
    heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return heading.group(1) if heading else fallback


def storage_html(body: str, source: str) -> str:
    try:
        import markdown
    except ImportError:
        raise PublishError("the Confluence destination needs the 'markdown' package: pip install markdown") from None
    converted = markdown.markdown(body, extensions=["tables", "fenced_code"], output_format="xhtml")
    note = f"<p><em>Published from {html.escape(source)} in the knowledge repository. Edit it there; changes made here are overwritten.</em></p>"
    return note + converted


def confluence_pages(root: Path, files: list[Path]) -> list[tuple[Path, str, str]]:
    """(file, unique title, storage-format body) for each Markdown file."""
    drafts = []
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
        rel = relative(path, root)
        drafts.append((path, page_title(frontmatter, body, path.stem), rel, body))
    counts: dict[str, int] = {}
    for _, title, _, _ in drafts:
        counts[title.lower()] = counts.get(title.lower(), 0) + 1
    pages = []
    for path, title, rel, body in drafts:
        if counts[title.lower()] > 1:  # titles are unique per space: say which file each one is
            title = f"{title} ({rel.removesuffix('.md')})"
        pages.append((path, title[:255], storage_html(body, f"{root.name}/{rel}")))
    return pages


def publish_confluence(root: Path, files: list[Path], env: dict[str, str], dry_run: bool) -> tuple[list[str], list[str]]:
    """One page per Markdown file, created or updated by title under an optional parent page."""
    pages = confluence_pages(root, files)
    if not pages:
        raise PublishError("nothing to publish: no Markdown files (Confluence pages are made from .md files)")
    if dry_run:
        return [f"{relative(path, root)} -> page '{title}'" for path, title, _ in pages], []

    api = f"{env['CONFLUENCE_URL'].strip().rstrip('/')}/rest/api"
    auth = {"Authorization": f"Bearer {env['CONFLUENCE_TOKEN'].strip()}"}
    space = env["CONFLUENCE_SPACE_KEY"].strip()
    parent = env.get("CONFLUENCE_PARENT_PAGE_ID", "").strip()
    done: list[str] = []
    failed: list[str] = []
    for path, title, content in pages:
        try:
            query = urllib.parse.urlencode({"type": "page", "spaceKey": space, "title": title,
                                            "expand": "version,body.storage"})
            found = call_json("GET", f"{api}/content?{query}", headers=auth).get("results", [])  # type: ignore[union-attr]
            body = {"representation": "storage", "value": content}
            if found:
                page = found[0]
                if page.get("body", {}).get("storage", {}).get("value", "").strip() == content.strip():
                    done.append(f"{relative(path, root)} -> '{title}' (unchanged)")
                    continue
                call_json("PUT", f"{api}/content/{page['id']}", headers=auth, body={
                    "id": page["id"], "type": "page", "title": title,
                    "version": {"number": page["version"]["number"] + 1}, "body": {"storage": body},
                })
                done.append(f"{relative(path, root)} -> '{title}' (updated)")
            else:
                create: dict[str, object] = {"type": "page", "title": title, "space": {"key": space},
                                             "body": {"storage": body}}
                if parent:
                    create["ancestors"] = [{"id": parent}]
                call_json("POST", f"{api}/content", headers=auth, body=create)
                done.append(f"{relative(path, root)} -> '{title}' (created)")
        except PublishError as error:
            failed.append(f"{relative(path, root)}: {error}")
    return done, failed


# --- sharepoint -----------------------------------------------------------------------------

SIMPLE_UPLOAD_LIMIT = 4_000_000  # Graph's single-request upload; knowledge files are far smaller


def publish_sharepoint(root: Path, files: list[Path], env: dict[str, str], dry_run: bool) -> tuple[list[str], list[str]]:
    """Files go to a folder in a SharePoint document library through Microsoft Graph."""
    site_url = urllib.parse.urlparse(env["SHAREPOINT_SITE_URL"].strip())
    if not (site_url.hostname and site_url.path.strip("/")):
        raise PublishError("SHAREPOINT_SITE_URL must include the site, e.g. https://contoso.sharepoint.com/sites/Knowledge")
    library = env.get("SHAREPOINT_LIBRARY", "").strip() or "Documents"
    folder = (env.get("SHAREPOINT_FOLDER", "").strip() or "knowledge").strip("/")
    plan = [(path, f"{folder}/{relative(path, root)}") for path in files]
    if dry_run:
        return [f"{relative(p, root)} -> {site_url.hostname}{site_url.path.rstrip('/')} / {library} / {dest}" for p, dest in plan], []

    login = (env.get("SHAREPOINT_LOGIN_URL", "").strip() or "https://login.microsoftonline.com").rstrip("/")
    graph = (env.get("SHAREPOINT_GRAPH_URL", "").strip() or "https://graph.microsoft.com").rstrip("/")
    token_form = urllib.parse.urlencode({
        "client_id": env["SHAREPOINT_CLIENT_ID"].strip(),
        "client_secret": env["SHAREPOINT_CLIENT_SECRET"].strip(),
        "scope": f"{graph}/.default",
        "grant_type": "client_credentials",
    }).encode("ascii")
    token_url = f"{login}/{urllib.parse.quote(env['SHAREPOINT_TENANT_ID'].strip())}/oauth2/v2.0/token"
    token = json.loads(request("POST", token_url, data=token_form,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})).get("access_token")
    if not token:
        raise PublishError("the token endpoint answered without an access_token")
    auth = {"Authorization": f"Bearer {token}"}

    site = call_json("GET", f"{graph}/v1.0/sites/{site_url.hostname}:{quote_path(site_url.path.rstrip('/'))}", headers=auth)
    drives = call_json("GET", f"{graph}/v1.0/sites/{site['id']}/drives", headers=auth).get("value", [])  # type: ignore[index,union-attr]
    drive = next((d for d in drives if d.get("name", "").lower() == library.lower()), None)  # type: ignore[union-attr]
    if drive is None:
        names = ", ".join(d.get("name", "?") for d in drives) or "none"  # type: ignore[union-attr]
        raise PublishError(f"no document library named {library!r} on that site (found: {names})")

    done: list[str] = []
    failed: list[str] = []
    for path, dest in plan:
        try:
            content = path.read_bytes()
            if len(content) > SIMPLE_UPLOAD_LIMIT:
                raise PublishError(f"{len(content)} bytes is over the {SIMPLE_UPLOAD_LIMIT}-byte single-request limit")
            request("PUT", f"{graph}/v1.0/drives/{drive['id']}/root:/{quote_path(dest)}:/content"
                           "?@microsoft.graph.conflictBehavior=replace",
                    headers={**auth, "Content-Type": "application/octet-stream"}, data=content)
            done.append(f"{relative(path, root)} -> {library}/{dest}")
        except PublishError as error:
            failed.append(f"{relative(path, root)}: {error}")
    return done, failed


PUBLISHERS = {"databricks": publish_databricks, "confluence": publish_confluence, "sharepoint": publish_sharepoint}


# --- main -----------------------------------------------------------------------------------

def write_summary(destination: str, done: list[str], failed: list[str], dry_run: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    verb = "would write" if dry_run else "wrote"
    lines = [f"### publish to {destination}: {verb} {len(done)}, failed {len(failed)}", ""]
    lines += [f"- {entry}" for entry in done[:50]]
    lines += [f"- FAILED {entry}" for entry in failed]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish knowledge/ to an external destination.")
    parser.add_argument("destination", choices=sorted(PUBLISHERS))
    parser.add_argument("--source", default="knowledge", help="directory to publish (default: knowledge)")
    parser.add_argument("--check", action="store_true", help="only check that secrets and settings are set")
    parser.add_argument("--dry-run", action="store_true", help="list what would be written; send nothing")
    args = parser.parse_args(argv)
    environment = dict(os.environ if env is None else env)
    try:
        check(args.destination, environment, dry_run=args.dry_run)
        if args.check:
            print(f"ok: {args.destination} secrets and settings are set" if not args.dry_run
                  else f"ok: {args.destination} settings are set")
            return 0
        root = Path(args.source)
        done, failed = PUBLISHERS[args.destination](root, source_files(root), environment, args.dry_run)
    except PublishError as error:
        print(f"::error::{str(error).splitlines()[0]}" if os.environ.get("GITHUB_ACTIONS") else "", end="")
        print(error, file=sys.stderr)
        return 2 if str(error).startswith("Cannot publish") else 1
    verb = "would write" if args.dry_run else "wrote"
    for entry in done:
        print(entry)
    for entry in failed:
        print(f"FAILED {entry}", file=sys.stderr)
    print(f"{args.destination}: {verb} {len(done)}, failed {len(failed)}")
    write_summary(args.destination, done, failed, args.dry_run)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
