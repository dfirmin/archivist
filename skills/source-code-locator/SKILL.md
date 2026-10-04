---
name: source-code-locator
description: >
  Clones a source repo and finds the SQL, dbt or ETL files that define named views or
  tables. Use in the code-logic enrichment method, when the enricher has entity names and
  the repos that build them.
allowed-tools: Bash, Read, Grep, Glob
---

Turn a repo URL and a list of entity (view or table) names into the files that define
them. The clone is read-only evidence: nothing is staged, committed or pushed in it.

## 1. Clone

One shallow clone per repo, under `/tmp`:

```bash
CLONE_DIR=$(mktemp -d /tmp/src-repo-XXXXXXXX)
git clone --depth=1 "<repo-url>" "$CLONE_DIR"
git -C "$CLONE_DIR" rev-parse --short HEAD   # the commit every citation names
```

A failed clone marks that repo **unreachable**: record the repo and git's one-line error,
move to the next repo. The container's git login is the only credential; secrets and
`.env` files in a clone stay unread.

Done when each repo is cloned (with its short commit) or marked unreachable.

## 2. Find the definition files

For each view name, case-insensitively, over `*.sql`, `*.py`, `*.yml`, `*.yaml`:

```bash
grep -rliE --include="*.sql" --include="*.py" --include="*.yml" --include="*.yaml" \
  "<VIEW_NAME>" "$CLONE_DIR"
```

A file that **defines** the view (`CREATE ... VIEW <name>`, `INSERT INTO <name>`, a dbt
model named for it) outranks a file that only reads from it. When nothing matches, widen
in order:

1. Drop a trailing `_SV`, `_MV`, `_V` or `_VW` and search the stem.
2. Match file names: `find "$CLONE_DIR" -iname "*<stem>*"`.
3. In a dbt repo, look under `models/**/*.sql` for the stem.

## 3. Read the repo's shape

| Repo shape | Where the logic lives |
|---|---|
| Pure SQL (`*.sql`, no `models/`) | The SQL files themselves |
| dbt (`dbt_project.yml`) | `models/**/*.sql`; `schema.yml` / `sources.yml` for column descriptions |
| Python-orchestrated ETL | Python sets stage order and parameters; the SQL holds the logic |

A view is often assembled across several files: header, lines, lookups, volatile or temp
tables. Follow the chain to the **final assembly** statement that produces the view, and
read every file in it.

Done when each view maps to its definition files (final assembly first), or is recorded
as not found.

## 4. Clean up

```bash
rm -rf "$CLONE_DIR"
```

Remove the clone after the last read, on success and on failure alike.
