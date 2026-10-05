---
title: "FW: RE: what is LEGACY_FEED??"
---

From: Priya (Data Platform)
Sent: Tuesday
Subject: FW: RE: what is LEGACY_FEED??

> Does anyone own LEGACY_FEED? It still lands every night but nothing downstream reads it as
> far as I can tell.

Reply from Marco: LEGACY_FEED is the old flat-file export from the mainframe claims intake. It
has one row per claim header, CLAIM_NO is the key. We stopped using it for reporting when the
CRM migration finished, but finance still pulls CLAIM_AMT_TOT from it at quarter end.

Not sure who should own it now. Possibly billing?
