---
name: file-gap-issues
description: >
  Files one GitHub issue per `okfx_gaps` entry on a group's concepts, created or updated by exact
  title, titled and labelled as the target's publishing contract says, linked to the run's
  pull request, and closes the open issue of each applicable kind the concept no longer has.
  Use after the PR exists.
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

Use the REST API through `gh api` (the `gh issue`/`gh label` subcommands need GraphQL, which
some tokens and hosts do not allow). Write each body to a file first.

Each label exists before it is used ("already exists" is fine):

```bash
gh api -X POST "repos/$REPO/labels" -f name="<label>" 2>/dev/null || true
```

Find an open issue whose title equals the rendered title exactly. The search API matches
loosely, so compare titles exactly yourself:

```bash
gh api "repos/$REPO/issues?state=open&per_page=100" --paginate \
  --jq '.[] | select(.pull_request == null) | select(.title == "<title>") | .number'
```

No match → create; a match → update the body and add the labels:

```bash
gh api -X POST "repos/$REPO/issues" -f title="<title>" -F body=@<body file> \
  -f "labels[]=<label 1>" -f "labels[]=<label 2>" --jq '"\(.number) \(.html_url)"'

gh api -X PATCH "repos/$REPO/issues/<n>" -F body=@<body file> --jq .html_url
gh api -X POST "repos/$REPO/issues/<n>/labels" -f "labels[]=<label 1>" -f "labels[]=<label 2>" > /dev/null
```

Done when every gap has an issue, each reported as created or updated with its number.

## 4. Close resolved gaps

For each concept, take every kind in the gap-kinds contract that this run's fleet judged on it
(the run plan's `scope.kinds` when that is a list, otherwise every enabled kind whose
`applies_to` holds the concept's type id) and that has no `okfx_gaps` entry now. Render that
kind's title as in §2. An open issue with exactly that title is resolved: comment and close it.

```bash
gh api -X POST "repos/$REPO/issues/<n>/comments" -f body="No longer present as of PR #<number>." > /dev/null
gh api -X PATCH "repos/$REPO/issues/<n>" -f state=closed -f state_reason=completed --jq .html_url
```

Never close an issue for a kind outside this run's scope. Done when each resolved kind's open
issue is reported closed, or reported as having none.
