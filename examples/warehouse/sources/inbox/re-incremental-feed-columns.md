---
title: "RE: incremental feed - which columns change?"
---

Thread exported from Teams, #data-support

**Jo (analytics):** quick one, in CUSTCASE_INCRMTL_SV which columns actually change between loads? we keep double counting

**Sam (DW team):** only the status cols. CASE_STATUS_CD and CASE_STATUS_TS get updated when a case moves, LAST_UPDT_TS is set on every change. everything else is insert-only. dedupe on CASE_ID + LAST_UPDT_TS and take the latest

**Jo:** and deleted cases?

**Sam:** they never delete, a withdrawn case just gets CASE_STATUS_CD = 'W'

**Jo:** 👍 thx
