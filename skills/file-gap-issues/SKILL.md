---
name: file-gap-issues
description: >
  One GitHub issue per `okfx_gaps` entry on a group's concepts, created or updated by exact
  title, titled and labelled as the target's publishing contract says, linked to the run's
  pull request. Use after the PR exists.
allowed-tools: Bash, Read
---

Run from the knowledge-repo root, with the PR number and URL from **open-pull-request** and
the repo slug it used. Keep `https_proxy` if it is set. Credentials stay out of output.

The optional publishing contract (per **target-contracts**) shapes the issues; `issues.enabled:
false` means file none. Defaults are given for every rule.

## 1. Collect the gaps

Take the concepts the conductor names (this group). Each `okfx_gaps` entry is one issue. A
gap's priority comes from its kind in the gap-kinds contract. A kind missing from that
contract stops filing for that gap: report it.

## 2. Render one issue

**Title:** `issues.title` with `{field}` filled from the concept's frontmatter and `{kind}`
from the gap. Default `{title} — {kind}`. Example from a contract:
`{okfx_policy_area}: {title} — {kind}` → `finance: Travel Policy — missing_section`.

**Labels**, deduplicated, in `issues.labels` order. Each entry is a frontmatter field (a
list contributes each item) or one of `priority`, `origin`, `kind`. Default:
`[tags, priority, origin, kind]`. Priority is unprefixed (`high`, not `priority:high`).

**Body:**

```markdown
## Concept
<concept path>
Title: <title>
<one line per issues.summary_fields entry: "<field>: <value>">
Confidence: <okfx_confidence>

## Gap (<origin>)
<kind>
<description, verbatim>

## Routing
Owner: <value of issues.routing_field, or "unassigned">

## Pull Request
PR #<number> — <url>
```

## 3. Create or update, by exact title

Each label exists before it is used:

```bash
gh label create "<label>" --repo "$REPO"   # "already exists" is fine
```

Find an open issue whose title equals the rendered title exactly:

```bash
gh issue list --repo "$REPO" --state open --search "\"<title>\" in:title" --json number,title
```

No exact match → `gh issue create --repo "$REPO" --title … --body-file … --label …`.
An exact match → `gh issue edit <n> --repo "$REPO" --body-file … --add-label …`.

Done when every gap has an issue, each reported as created or updated with its number.
