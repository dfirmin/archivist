# 0011 — No document waits for another

Status: accepted, 2026-10-07.

## Context

A target could give an intake class `mode: enrich-only`: with no existing concept, the document
stayed in the inbox "awaiting its primary document". Both examples used it for amendments. It
had three problems:

- **"Primary" is hard to define.** Which document is the main one for a concept is a judgement
  the contracts only hinted at (an `ordering` line), and authors extended the wait to documents
  no rule covered: a live Pi run (2026-10-07) left a transcript extract about CLAIM_PMT_SV in the
  inbox "awaiting a primary document", then created the concept from it in the next round.
- **Knowledge sat unused.** An amendment stating a whole new rule (16 weeks of parental leave
  from 2027-01-01) stayed invisible until someone documented the old rule.
- **It needed machinery**: held documents in the run loop, "left in the inbox" in reports, a
  done-when exception.

## Decision

1. **No document waits for another.** With no existing concept, a document creates it from what
   it supports, whatever kind of document it is: its sections are written from it and the rest
   are stubbed (PARTIAL CREATE). A later document about the same instance finds it by identity
   (ADR 0005) and adds to it (ENRICH). The gap fleet reports the stubs.
2. **`enrich-only` is read as `partial`.** Contracts that declare it stay valid; both examples
   now say `partial`.
3. A document still in the inbox after the producing stage is a failure the conductor records,
   not an outcome. The author's report no longer has "Left in inbox". The runner's hold of a
   document a session left (serial loop) or left twice (parallel, ADR 0009) stays, as a guard
   against looping, not as a feature.
4. What cannot be placed is still quarantined (ADR 0005): a required value nothing supplies, out
   of scope, an ambiguous match. That is the place for "not enough to go on", with `needs`
   saying what would resolve it.

## Proof

docs/live-proof/2026-10-07.md: on `archivist-knowledge-01` the parental-leave amendment became a
grounded Parental Leave policy (rules, who it applies to, the exception; Purpose stubbed). On the
warehouse mirror the BR-HOM-022 amendment was quarantined by both harnesses: a business rule
needs its owners subject area and the email names only "homeowners"; the draft's `needs` carries
the new cutoff. Nothing was left in any inbox; every other outcome as before.
