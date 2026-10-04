---
title: CUSTCASE (Customer Case) - Essential Information
catalog_document_id: 249
---

# CUSTCASE (Customer Case) - Essential Information

CUSTCASE holds one row per customer support case opened in Sample CRM. Cases are loaded nightly
from the CRM extract and a case appears once it has been assigned a case number.

Grain: one row per case (CASE_ID). Closed cases are retained for seven years.

CASE_STATUS_CD values: O (open), P (pending customer), C (closed).

Use CUSTCASE_INCRMTL_SV for change-data loads; it carries only cases touched since the last run.
