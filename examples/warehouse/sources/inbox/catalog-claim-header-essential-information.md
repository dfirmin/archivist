---
title: CLAIM_HDR_SV (Claim Header) - Essential Information
catalog_document_id: 310
---

# CLAIM_HDR_SV (Claim Header) - Essential Information

CLAIM_HDR_SV holds one row per claim reported to the Sample Claims Platform, with the claim's
status, loss date, reported date and line of business. It is the starting point for claim
counts and for joining payments (CLAIM_PMT_SV) and exposure.

Grain: one row per claim (CLAIM_ID). A claim reopened after closing keeps its CLAIM_ID; the
reopen is visible in CLAIM_STATUS_CD and REOPEN_DT.

Loaded nightly from the Sample Claims Platform at 02:00 ET.

| Column | Meaning |
|--------|---------|
| CLAIM_ID | Claim identifier |
| LOB_CD | Line of business: AUTO, HOME, COMM |
| CLAIM_STATUS_CD | O open, C closed, R reopened |
| LOSS_DT | Date of loss |
| RPT_DT | Date the claim was reported |
| REOPEN_DT | Most recent reopen date, null if never reopened |

Known issue: claims migrated from the old platform before 2019 have RPT_DT equal to LOSS_DT.
