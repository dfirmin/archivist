# Publishing secrets and settings

This repository ships three ad hoc workflows that copy `knowledge/` somewhere else. None of them
runs on a schedule or on a push: you start one from **Actions > the workflow > Run workflow**.
Use the ones you need and delete the rest (the workflow file, and its entry in `secrets.yaml`).

GitHub cannot create a secret without a value, so none exist yet. Until the ones a workflow needs
are set, that workflow stops at its first step and lists what is missing. The full list, with
descriptions, is [`secrets.yaml`](secrets.yaml).

Set a value with the GitHub CLI (it prompts for the value, so it stays out of your shell history),
or in **Settings > Secrets and variables > Actions**:

```bash
gh secret set NAME            # a secret
gh variable set NAME          # a repository variable (not secret)
```

Try a workflow first with **Dry run** ticked: it lists what would be written, needs no secrets and
sends nothing.

## publish-databricks

| Kind | Name | What |
|---|---|---|
| secret | `DATABRICKS_HOST` | Workspace URL |
| secret | `DATABRICKS_TOKEN` | Token that can write to the destination |
| variable | `DATABRICKS_PATH` | Destination: `/Volumes/<catalog>/<schema>/<volume>/<folder>` or a workspace folder (also the `path` input) |

## publish-confluence

| Kind | Name | What |
|---|---|---|
| secret | `CONFLUENCE_URL` | Base URL the REST API lives under, without `/rest/api` |
| secret | `CONFLUENCE_TOKEN` | Bearer token (a Personal Access Token) |
| variable | `CONFLUENCE_SPACE_KEY` | Space the pages go to (also the `space_key` input) |
| variable, optional | `CONFLUENCE_PARENT_PAGE_ID` | Page they go under; the space root if unset |

One page is written per Markdown file, titled by the concept's `title`. A page that already has
that title in the space is updated; the rest are created. Two concepts with the same title get
their paths added to the title. Links between concepts are not rewritten.

## publish-sharepoint

| Kind | Name | What |
|---|---|---|
| secret | `SHAREPOINT_TENANT_ID` | Microsoft Entra tenant id |
| secret | `SHAREPOINT_CLIENT_ID` | App registration (client) id |
| secret | `SHAREPOINT_CLIENT_SECRET` | Client secret of that app registration |
| variable | `SHAREPOINT_SITE_URL` | Site, e.g. `https://contoso.sharepoint.com/sites/Knowledge` (also the `site_url` input) |
| variable, optional | `SHAREPOINT_LIBRARY` | Library name; `Documents` if unset |
| variable, optional | `SHAREPOINT_FOLDER` | Folder in the library; `knowledge` if unset |
| variable, optional | `SHAREPOINT_LOGIN_URL`, `SHAREPOINT_GRAPH_URL` | Only for a government cloud |

The workflow signs in as the app registration (client credentials), so the app needs Microsoft
Graph **application** permission to that site, ideally `Sites.Selected` granted on just this site
by a tenant admin. Whoever can grant it has to do that step; the workflow cannot.

## What these workflows do not do

- They copy the files that exist now. A concept removed from `knowledge/` stays at the destination
  until someone removes it there.
- They publish the branch you run them on.
- The runner is `ubuntu-latest`. For a self-hosted runner, or a proxy or private CA, edit the
  clearly marked runner sections at the top of each workflow; the engine never overwrites these
  files after seeding them.
