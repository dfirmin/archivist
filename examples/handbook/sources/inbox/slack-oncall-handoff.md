#platform-oncall — exported thread, Thu Oct 1 2026

[09:02] marco: ok so for the new folks, here's how we do the weekly oncall handoff 🧵
[09:03] marco: every monday 10am, outgoing person runs it. takes like 15 min
[09:03] jen: 10am ET right? not PT lol
[09:04] marco: ET yes
[09:05] marco: 1. post the handoff note in #platform-oncall using the template (open incidents, flaky alerts, anything weird)
[09:05] marco: 2. reassign the pager schedule override in PagerDuty to the incoming person
[09:06] marco: 3. walk through open tickets w/ incoming on a quick call
[09:07] jen: you forgot the dashboards
[09:07] marco: oh right - actually do this BEFORE the call: check the SLO dashboard and note anything burning error budget in the handoff note
[09:08] sam: do we still need to ack the test page?
[09:09] marco: yes!! last step: incoming person triggers a test page and acks it so we know paging works. if the test page doesn't arrive, tell the platform lead before the outgoing person signs off
[09:10] sam: 👍
[09:12] jen: also pls stop doing handoffs on friday, it's monday
[09:12] marco: monday. confirmed. lunch?
