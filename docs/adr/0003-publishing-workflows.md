# 0003 — Publishing workflows ship with the scaffold

Status: accepted, 2026-10-04

## Context

A target's `knowledge/` is the product, and people read it somewhere other than GitHub:
Databricks, Confluence, SharePoint. Getting it there is copying files, not judgement, and it
happens outside any engine run. Each team also keeps its own credentials for those systems.

## Decision

1. **`prepare-target` seeds three workflows** into `.github/workflows/`: `publish-databricks`,
   `publish-confluence`, `publish-sharepoint`. They are started by hand (`workflow_dispatch`);
   nothing runs on a push or a schedule. A repo owner uses the ones they need and deletes the rest.
2. **One script does the copying**, `.github/archivist/publish.py`: standard library only
   (Confluence also needs the `markdown` package, which its workflow installs). Credentials
   and settings arrive as environment variables from GitHub secrets, repository variables and
   workflow inputs; a path or id typed into an input reaches the script through the
   environment, never through the shell command line. `--dry-run` lists what would be written
   with no secrets and no network.
3. **Secrets are a manifest, not secrets.** GitHub cannot create a secret without a value, so
   the scaffold writes `.github/archivist/secrets.yaml` (every secret and variable per workflow)
   and `SECRETS.md` (the owner's checklist with `gh secret set` commands). Each workflow's first
   step names what is missing and stops, so an unconfigured workflow fails clearly. The engine
   does not call the secrets API and holds no credentials for these destinations.
4. **Seeded once, then the target's.** Like the starter contracts, the files are written when
   missing and never overwritten; an upgrade does not touch them and scaffold detection does not
   look for them. The runner (`runs-on`) and proxy or CA settings are marked stubs in each
   workflow for a self-hosted runner. A target scaffolded earlier receives the files the next
   time `prepare-target` runs, in the onboarding pull request.
5. **Settings live in variables and inputs, not in a contract.** The destinations are not
   `publishing.yaml` fields: that contract describes gap issues, and a destination is a
   property of a team's network, not of the knowledge. Revisit if a target needs the same
   destination settings read by an agent.
6. **Copy, never delete.** The workflows write the files that exist now. Removing a concept
   from `knowledge/` does not remove its published copy.

## Why deterministic

This is a CI output stage, not agent work: bytes (or Markdown converted to Confluence storage
format) go to a URL. There is no judgement to hand to an agent, and the step runs outside the
conductor. The consistency guardrail is a test: the names a workflow passes, the names the
script requires and the names in `secrets.yaml` must agree.

## Consequences

- The token that publishes a scaffold needs permission to write workflow files (the `workflow`
  scope of a classic personal access token, or Workflows: read and write for a fine-grained
  token or app). Without it the onboarding push is rejected.
- The script is tested offline against local fakes of each API. It has not run against a real
  Databricks workspace, Confluence or SharePoint site: a first run of each destination needs a
  live check by the team that owns it (start with Dry run).
- A fix to the script reaches an existing target only by re-seeding or copying the file; there
  is deliberately no overwrite.
