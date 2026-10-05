---
title: "Recording transcript: DB outage retro (Platform) — Oct 2"
---

Transcript (auto-generated). Speakers identified where possible.

[00:00:04] Dana Ruiz: ok I think we're recording. can everyone hear me
[00:00:07] Unknown: yep
[00:00:09] Dana Ruiz: cool. so, retro for tuesday's primary outage. um, Lev you were IC right
[00:00:13] Lev Sato: yeah I was incident commander, Priya was on the database side
[00:00:20] Priya Raman: hi all, sorry my camera's being weird
[00:00:24] Dana Ruiz: no worries. ok quick timeline then the changes
[00:00:31] Lev Sato: alert fired 2:14, we went to maintenance mode at like 2:20, announced in status channel at 2:22
[00:00:40] Lev Sato: the restart didn't work so we promoted the replica at 2:37
[00:00:46] Priya Raman: which honestly was too late. the runbook says wait 10 minutes before promoting and we waited longer because nobody owned the call
[00:00:58] Dana Ruiz: right so that's change number one. the incident commander decides on promotion, not whoever's at the keyboard
[00:01:05] Lev Sato: +1
[00:01:07] Unknown: [crosstalk] — sorry go ahead
[00:01:10] Dana Ruiz: and change two. we page the DBA on-call if the primary isn't back in 15 minutes
[00:01:16] Priya Raman: wait I thought we said 30 last time
[00:01:19] Dana Ruiz: we did say 30 in the draft, but no, it's 15. 30 is way too long for a customer-facing outage
[00:01:26] Priya Raman: ok 15, got it
[00:01:28] Lev Sato: DBA on-call is the #dba-oncall channel right, not the platform one
[00:01:32] Dana Ruiz: yes #dba-oncall
[00:01:35] Unknown: did someone order lunch for after this
[00:01:38] Lev Sato: lol not yet
[00:01:41] Dana Ruiz: ok last thing, the review itself. going forward every customer-facing incident gets a post-incident review within five business days, not two, two was never realistic
[00:01:52] Priya Raman: and that's for every team not just platform?
[00:01:55] Dana Ruiz: every team, it's going in the handbook as a platform-owned policy
[00:02:01] Lev Sato: makes sense
[00:02:03] Dana Ruiz: ok that's it, thanks all. Priya can you send the notes
[00:02:06] Priya Raman: yep will do
