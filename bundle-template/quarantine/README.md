# Quarantine

**Nothing in this directory is approved knowledge.** Each file here is a draft archivist could
not place in `knowledge/`, waiting for an owner to resolve it. Drafts here are not indexed,
scored or published.

Every draft says why in its frontmatter:

- `okfx_quarantine.reason` — what stopped it (for example: out of scope under the intake
  contract, a required value the reference data does not hold, or more than one existing
  concept it could belong to);
- `okfx_quarantine.needs` — what would resolve it;
- `okfx_quarantine.candidates` — the existing concepts it might belong to, when that was the
  question.

Its source documents wait in `sources/quarantine/`. Each draft also has an open GitHub issue
titled `Quarantined: <file name>`.

## Resolving a draft

1. Make the change `needs` asks for, by pull request: usually a contract or reference-data
   change in `contracts/` (an inventory row, an owner, a sharper grouping rule).
2. Requeue it:

   ```bash
   archivist requeue quarantine/<file>.md
   ```

   Its documents go back to `sources/inbox/` and the draft is deleted.
3. The next archivist run authors the documents under the updated contracts, runs every
   later stage and closes the issue.

Do not move a draft into `knowledge/` by hand: it would skip enrichment, verification, gap
checks and scoring, and `archivist check-concept` refuses it there. A document that should
never become knowledge can simply be deleted, with its draft.
