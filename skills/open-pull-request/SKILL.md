---
name: open-pull-request
description: >
  Pull request for the pushed run branch: reuse the open one or create it, and report
  its number and URL. Use after the branch is on origin.
allowed-tools: Bash, Read
---

Run from the knowledge-repo root. The repo slug is `TARGET_GITHUB_REPO` when set,
otherwise the owner and name of `origin`
(`https://github.com/example-org/<repo>.git` → `example-org/<repo>`). The head is the run
branch (`RUN_BRANCH`) and the base is `main`. Keep `https_proxy` if it is set. Credentials
stay out of output.

## 1. Reuse an open PR

```bash
gh pr list --repo "$REPO" --head "$RUN_BRANCH" --base main --state open --json number,url
```

A row means the PR exists. Refresh its body with the concepts the branch now changes
(the list and body in step 2) using `gh pr edit <number> --repo "$REPO" --body-file <body
file>`, report it as reused, and stop.

## 2. Otherwise create it

List the concepts this branch changed:

```bash
git diff --name-only origin/main...HEAD -- knowledge/ | grep -E '\.md$'
```

```bash
gh pr create --repo "$REPO" --head "$RUN_BRANCH" --base main \
  --title "archivist: $RUN_BRANCH" --body-file <body file>
```

Body:

```markdown
Archivist run on this branch.

Concepts:
- `<concept path>`
```

`gh pr create` prints the PR URL; the number is the trailing `/pull/<n>`.

Done when you hold the PR number and URL, and say whether it was created or reused.
