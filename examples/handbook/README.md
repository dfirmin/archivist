# Example: team handbook

Policies and runbooks owned by several teams, from clean documents and messy ones (forwarded
email, chat exports, rough notes, a recorded retro call). The non-data example: no reference
lookups decide structure; the document's content does.

## What it shows

| Feature | Where |
|---|---|
| Intake classes route documents to different concept types | `intake.yaml` → `policy-document`, `procedure-document` |
| Structure chosen by content | `concept-types.yaml` → `runbook` → `structure_rule` |
| Identity by title, with matching guidance | `policy` → `identity` |
| Composite identity | `runbook` → `identity: [title, okfx_team]` |
| Amendments wait for their policy | `policy-amendment` (`mode: enrich-only`) |
| Owner matching with aliases, and quarantine when nothing matches | `intake.yaml` → `scope`; `reference/teams.yaml` |
| Gaps judged only for one structure | `gap-kinds.yaml` → `missing_escalation`, `missing_rollback` |
| A call split into extracts by a rule the target writes | `intake.yaml` → `incident-review-call` (`mode: extract`) |

## Inbox and expected outcomes

Run the whole inbox (`archivist run-conductor <copy> --skip-publish`).

| Document | Kind | Expected outcome |
|---|---|---|
| `remote-work-policy.md` | clean | **new** Remote Work Policy (people-ops) |
| `expense-reimbursement-policy.md` | clean | **new** Expense Reimbursement Policy (finance-ops)… |
| `fwd-meal-limit-change.md` | forwarded email, amendment | …same group: meal limit **updated** to the final amount, the change stated |
| `re-parental-leave-update.md` | email, amendment | **left in the inbox**: awaiting a parental leave policy |
| `deploy-web-app.md` | clean | **new** runbook, routine-procedure (platform) |
| `database-outage-response.md` | clean | **new** runbook, incident-response (platform)… |
| ↳ extract from `2026-10-02-db-outage-retro-call.md` (outage runbook) | transcript | …then **updated**: the incident commander decides on promotion; page `#dba-oncall` after 15 minutes (the call corrects 30 to 15) |
| ↳ extract from `2026-10-02-db-outage-retro-call.md` (post-incident reviews) | transcript | **new** Post-Incident Review policy (platform): a review within five business days for every customer-facing incident |
| `phishing-incident-notes.md` | rough notes | **new** runbook, incident-response (security) |
| `slack-oncall-handoff.md` | chat export | **new** runbook, routine-procedure (platform) |
| `backfill-pipeline-partition.md` | clean | **new** runbook, routine-procedure (data-engineering); `missing_rollback` judged |
| `social-media-guidelines.md` | clean, unknown owner | **quarantined** stub: Marketing is not in teams |
| `2026-10-02-db-outage-retro-call.md` | transcript | moved to `sources/processed/`; lunch and status chatter dropped |

## Last tested

2026-10-05, engine commit `448ee47` (`--engine current`). A full inbox run (handbook pipeline)
on the commit before found two defects: two runbooks for one outage, and the phishing notes
sent to the extractor. After the fixes, a focused run of the outage document with the retro
call, the phishing notes, the chat export and the parental-leave amendment matched the table,
and the amendment waited in each of three repeat runs. Details:
`docs/live-proof/2026-10-05.md` in the engine.
