# Example: data warehouse

Business context for a fictional insurer's warehouse, in one target: business views, subject
areas, **metric definitions** and **business rules**, with meeting transcripts split by the
extractor. It is the "everything in one target" example.

## What it shows

| Feature | Where |
|---|---|
| Inventory-driven scope, and quarantine for what it rejects | `intake.yaml` → `scope`; `reference/inventory.csv` |
| Identity from a list field (`match: any`) | `concept-types.yaml` → `business-view-group-overview` (`okfx_physical_views`) |
| Identity from a reference code | `metric-definition` (`okfx_metric_code` from `reference/metrics.csv`) |
| Composite identity (`match: all`) | `business-rule` (`okfx_rule_id` + `okfx_line_of_business`) |
| Structure chosen by looking something up | `subject-area-overview` → `structure_rule` (archetype in `owners.yaml`) |
| Structure chosen by content | `metric-definition` → ratio-metric or count-metric |
| Partial documents fill only their sections | `intake.yaml` → classes with `mode: partial` |
| Amendments wait for their rule | `intake.yaml` → `rule-amendment` (`mode: enrich-only`) |
| A required value never inferred | `business-rule` → `okfx_line_of_business` |
| Meeting transcripts split into topic extracts | `intake.yaml` → `meeting-transcript` (`mode: extract`) |
| Code-extracted logic (enrichment) | `structures/data-view-group.yaml` → `Code-Extracted Logic` |
| Gaps that depend on the structure chosen | `gap-kinds.yaml` → `missing_formula_part` |

## Inbox and expected outcomes

Run the whole inbox (`archivist run-conductor <copy> --pipeline no-code --skip-publish`).
Transcripts are extracted in the first session; their extracts join the groups below.

| Document | Kind | Expected outcome |
|---|---|---|
| `catalog-custcase-essential-information.md` | clean | **new** Customer Case view group (CUSTCASE + CUSTCASE_INCRMTL_SV), companions for both views |
| `catalog-custcase-code-sets.md` | clean, partial | same group as above (catalog parent): Code Set Information |
| `re-incremental-feed-columns.md` | Teams thread | same group: which columns change, dedupe rule, status `W` |
| `catalog-customer-care-subject-area.md` | clean | **new** Customer Care subject-area overview (data structure) |
| `case-handling-process-overview.md` | clean | **new** Case Handling Process overview (process structure, by archetype lookup) |
| `catalog-claim-header-essential-information.md` | clean | **new** Claim Header view group in `claims` |
| `metric-loss-ratio.md` | clean | **new** Loss Ratio metric, ratio-metric; denominator written premium… |
| ↳ extract from `2026-09-30-claims-dw-office-hours.md` (loss ratio) | transcript | …then **updated**: denominator is earned premium (`EARNED_PREM_AMT`) from the July close, the change stated |
| `kpi-open-claims-email.md` | messy email | **new** Open Claim Count metric, count-metric, excludes claims reported in the last 24 h… |
| ↳ extract from `2026-10-03-rules-triage-call.md` (open claims) | transcript | …then **updated**: 48 h from the October 12 deck |
| `br-clm-014-auto-total-loss.md` | clean | **new** rule BR-CLM-014 (auto), threshold 75% |
| `memo-total-loss-threshold-change.md` | amendment | same group: **updated** to 70% for losses from 2027-01-01, 75% before |
| ↳ extract from `2026-10-03-rules-triage-call.md` (BR-CLM-014) | transcript | **updated**: leased-vehicle exception from 2026-11-01 |
| ↳ extract from `2026-09-30-claims-dw-office-hours.md` (CUSTCASE_INCRMTL_SV) | transcript | Customer Case **updated**: LAST_UPDT_TS is UTC |
| ↳ extract from `2026-09-30-claims-dw-office-hours.md` (CLAIM_PMT_SV) | transcript | **new** CLAIM_PMT_SV view group, partial (PMT_TYPE_CD values, grain); titled by the view name, since the call gives no business name |
| ↳ extract from `2026-09-30-claims-dw-office-hours.md` (LEGACY_FEED) | transcript | **quarantined** stub: unresolved subject area for LEGACY_FEED |
| `fw-legacy-feed-question.md` | messy email | **quarantined** stub: unresolved subject area for LEGACY_FEED |
| `metric-policy-churn-rate.md` | draft | **quarantined** stub: no metrics row for Policy Churn Rate |
| `br-clm-031-salvage-notes.md` | working notes | **quarantined** draft: no line of business stated (`okfx_line_of_business` missing) |
| `re-br-hom-022-roof-age.md` | amendment | **left in the inbox**: awaiting BR-HOM-022 (home) |
| `2026-10-01-claims-team-sync.md` | transcript, small talk only | **quarantined** stub: no topic the extract rule keeps |
| each transcript | transcript | moved to `sources/processed/`; every quoted line found verbatim in it; small talk dropped |

The enricher's `code-logic` method needs the code repos in `inventory.csv`, which are
fictional; use the `no-code` pipeline unless you point them at real repos.

## Last tested

2026-10-05, engine commit `448ee47` (`--engine current`, pipeline `no-code`): every document
ended as the table says. 8 authored concepts with their companions, 5 quarantined, 1 held. All
58 quoted lines in the 8 extracts were found verbatim in their transcripts. Details and the
defects fixed on the way: `docs/live-proof/2026-10-05.md` in the engine.
