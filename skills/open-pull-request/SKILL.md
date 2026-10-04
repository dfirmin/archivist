---
name: open-pull-request
description: >
  Opens the pull request for the pushed run branch, or reuses the open one, and reports
  its number and URL. Use after the branch is on origin.
allowed-tools: Bash, Read
---

Run from the knowledge-repo root. The repo slug is `TARGET_GITHUB_REPO` when set,
otherwise the owner and name of `origin`
(`https://github.com/example-org/<repo>.git` → `example-org/<repo>`). The head is the run
branch (`RUN_BRANCH`) and the base is `main`. Keep `https_proxy` if it is set. Credentials
stay out of output.

Use the GitHub REST API through `gh api`, not `gh pr …`: the `pr` subcommands need GraphQL,
which some tokens and hosts do not allow; REST works wherever `gh` does.

```bash
REPO=$(git remote get-url origin | sed -E 's#(\.git)?$##; s#.*github\.com[/:]##')
OWNER=${REPO%%/*}
```

## 1. Reuse an open PR

```bash
gh api "repos/$REPO/pulls?head=$OWNER:$RUN_BRANCH&base=main&state=open" --jq '.[] | "\(.number) \(.html_url)"'
```

A line means the PR exists. Refresh its body with the concepts the branch now changes (the
list and body in step 2), report it as reused, and stop:

```bash
gh api -X PATCH "repos/$REPO/pulls/<number>" -F body=@<body file> --jq .html_url
```

## 2. Otherwise create it

List the concepts this branch changed:

```bash
git diff --name-only origin/main...HEAD -- knowledge/ | grep -E '\.md$'
```

```bash
gh api -X POST "repos/$REPO/pulls" -f title="archivist: $RUN_BRANCH" -f head="$RUN_BRANCH" \
  -f base=main -F body=@<body file> --jq '"\(.number) \(.html_url)"'
```

Body:

```markdown
Archivist run on this branch.

Concepts:
- `<concept path>`
```

Done when you hold the PR number and URL, and say whether it was created or reused.
