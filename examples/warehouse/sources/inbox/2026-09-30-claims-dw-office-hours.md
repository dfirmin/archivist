---
title: "Teams meeting transcript — DW office hours (claims + customer care), Sep 30"
---

WEBVTT-derived transcript. Auto-captions; speaker labels as Teams recorded them.

00:00:02 Sam Ortiz
ok we're live, um, office hours, drop your questions

00:00:06 Jo Park
hi, can you hear me? I'm on the train so sorry if I cut out

00:00:11 Sam Ortiz
yep loud and clear

00:00:14 Jo Park
ok so first one, LAST_UPDT_TS on CUSTCASE_INCRMTL_SV, is that UTC or eastern

00:00:19 Sam Ortiz
it's UTC. everything on the incremental views is UTC, the base CUSTCASE view is eastern, which, yeah, I know

00:00:26 Jo Park
ugh ok that explains the off by four hours thing

00:00:31 Mei Chen
can I jump in on loss ratio

00:00:33 Sam Ortiz
go for it Mei

00:00:35 Mei Chen
the loss ratio page still says written premium in the denominator

00:00:39 Sam Ortiz
right, that's how it's always been

00:00:42 Mei Chen
no — finance changed it in Q3, the denominator is earned premium now, not written. starting with the July close

00:00:49 Sam Ortiz
oh. ok so earned premium from POLICY_EXPOSURE_SV, EARNED_PREM_AMT

00:00:53 Mei Chen
yes exactly, EARNED_PREM_AMT. the page needs fixing

00:00:57 Unknown
sorry who's presenting

00:01:00 Sam Ortiz
nobody, it's office hours, ask away

00:01:04 Raj Iyer
ok mine is CLAIM_PMT_SV, what are the PMT_TYPE_CD values

00:01:08 Sam Ortiz
L is loss payment, E is expense, um, legal and adjuster fees go under E, and S is salvage recovery which comes in as a negative amount

00:01:17 Raj Iyer
negative, got it. one row per payment?

00:01:20 Sam Ortiz
one row per payment transaction, PMT_ID, and a payment can be voided, then there's a second row with VOID_IND Y

00:01:27 Jo Park
also does anyone know what LEGACY_FEED is, I saw it in the catalog

00:01:31 Sam Ortiz
it's the old mainframe claims extract, one row per claim, nobody owns it, finance still pulls a total from it at quarter end

00:01:38 Jo Park
weird ok

00:01:40 Mei Chen
are we doing the offsite in november or is that cancelled

00:01:43 Sam Ortiz
no idea, ask Dana. ok anything else? going once

00:01:47 Sam Ortiz
cool, thanks everyone
