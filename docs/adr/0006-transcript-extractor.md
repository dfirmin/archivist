# 0006 — An extractor turns one noisy multi-topic document into verbatim topic extracts

Status: proposed, 2026-10-05. Accepted once proven live on two targets.

## Context

Meeting transcripts are where much business context actually gets said, and they are the worst
input the engine sees. A one-hour call has auto-caption noise ("um", repeated words, a speaker
shown as `Unknown`), crosstalk, scheduling and small talk, and corrections later in the call
("actually no, it's 90 days, not 60"). Worse for the engine, one call covers several things:
a view's dedupe rule, a metric's definition, a rule exception.

The author's model is *one group of documents → one concept*. A transcript is *one document →
many concepts*. Handing it to the author forces one of two failures: it picks one topic and the
rest is lost, or it writes everything into one concept and identity (ADR 0005) can no longer
place it. The same shape appears in long exports that cover many topics (a Confluence space
page, a chat channel dump), and it is the `split` case ADR 0005 left open.

Noise itself is not the problem: the author already handles forwarded email and chat exports.
The problem is the split.

## Decision

1. **A new support agent, the extractor,** runs on a document before it is planned. It writes one
   **extract** per topic into `sources/inbox/` and moves the original to `sources/processed/`.
   Extracts are ordinary inbox documents: the planner groups them, the author places each one by
   identity (update, new or quarantine), and every later stage runs as it does today. Nothing
   downstream knows a transcript was involved.

2. **Extraction selects; it never summarises.** An extract holds the passages about one topic,
   quoted verbatim with speaker and timestamp, in transcript order, under a one-line statement of
   what they are about. Noise is removed by leaving it out, never by rewording what was said. A
   later correction is quoted together with what it corrects, in order, so the author's existing
   rule (the later statement wins, and says what changed) applies. Each extract records its origin
   so citations stay honest: the concept cites the extract, the extract names the transcript.

   ```markdown
   ---
   title: "CUSTCASE_INCRMTL_SV — dedupe and status changes"
   extracted_from: sources/processed/2026-10-02-dw-office-hours.md
   ---

   About: how CUSTCASE_INCRMTL_SV rows change between loads and how to dedupe them.

   > [00:12:31] Sam Ortiz: only the status columns change, CASE_STATUS_CD and the timestamp
   > [00:12:44] Jo Park: so we dedupe on CASE_ID plus LAST_UPDT_TS?
   > [00:12:47] Sam Ortiz: yeah take the latest
   ```

   The extractor checks every quoted line against the transcript (`grep -F`) before it finishes,
   and its report lists the topics extracted and what it dropped, in a phrase each ("scheduling",
   "lunch").

3. **The contract decides what is worth extracting, and which documents need it.** The intake
   contract gains a class mode, `extract`, and a class field `extract` with the rule:

   ```yaml
   classes:
     - id: meeting-transcript
       description: A recorded meeting or call, as an exported transcript.
       mode: extract
       extract: >-
         Keep passages that define, change or question a physical view, a metric or a business
         rule, one extract per view, metric or rule. Drop scheduling, introductions and small talk.
   ```

   A class with `mode: extract` names no concept type or sections; validation enforces that. A
   target without such a class never runs the extractor, so no existing target changes.

4. **Where it runs.** The planner, which already reads every inbox document to scope it, also
   classifies just enough to spot documents of an `extract` class and lists them as the first
   group, slug `extract`, ahead of `out-of-scope` (ADR 0005). The conductor dispatches the
   extractor once per document in that group and ends the session; the next session's planner
   sees the extracts in the inbox and plans them like any other document. A run that names one
   document (`--inbox-file`) is planned too when the target declares an `extract` class, so a
   transcript named directly is never handed to the author. The profile names the extractor as a
   second support agent next to the planner (`extractor:`), so it joins the roster only of runs
   that author from the inbox.

5. **Nothing extractable is quarantined.** A transcript with no topic the extract rule keeps goes
   to `quarantine/` as a stub (ADR 0005 §3) with the reason "no topic the extract rule keeps";
   an owner can widen the rule and requeue it. Topics that are relevant but out of scope (a view
   with no inventory row) are still extracted; the author then quarantines that extract with the
   specific reason, which is more useful than quarantining the whole call.

6. **Re-extraction replaces.** Extracts are named `<transcript stem>--<topic slug>.md`. A requeued
   transcript produces extracts with the same names where the topics are the same, and an extract
   still in the inbox with that name is replaced.

## Deterministic steps added

None. The quote check is an agent step (a `grep -F` per line). If live runs show the extractor
paraphrasing or inventing a quote despite it, a `check-extract` command (every quoted line is a
substring of the named transcript) is the first candidate, with its own ADR, the same path
`check-concept` took.

## Alternatives considered

- **Let the author handle transcripts.** Rejected for the split reason above; it also makes the
  author's prompt carry a second job on every run.
- **The extractor writes concepts directly.** Rejected: it would duplicate the author's placement,
  structure and grounding rules (one place per instruction), and skip identity.
- **Summarised extracts.** Rejected: a summary is the extractor's words, and the author would be
  grounding concepts in text no one said. Verbatim quotes keep the chain checkable.

## Consequences

- `schemas/contracts/intake.schema.json`: `mode` gains `extract`; classes gain `extract`
  (required when the mode is `extract`); cross-check that an `extract` class names no
  `concept_type` or `sections`.
- `agents/extractor.md` (Sonnet), a profile `extractor:` entry, roster and run-plan support; the
  planner's reply gains the `extract` group; the conductor's queue step learns to end the session
  after extraction.
- `examples/warehouse` gains a `meeting-transcript` class and three or four mocked transcripts
  (auto-caption noise, crosstalk, an unknown speaker, a mid-call correction, an out-of-scope
  topic, pure small talk) alongside the new metric and business-rule concept types.
- Live proof: on the warehouse, a transcript covering an existing view, a new metric and an
  out-of-scope view produces three extracts; one updates the view's concept, one creates the
  metric, one is quarantined; every quote in every extract is in the transcript; the correction
  wins in the concept. A transcript of only small talk is quarantined. On a second target, a
  transcript class in the handbook (a retro or incident review) proves the contract, not the
  engine, decides what is kept. Each extraction judgement is repeated three times.
- File formats (`.vtt`, `.docx`, `.pdf`) are a separate decision; Teams transcripts are commonly
  exported as `.vtt` or `.docx`, so they will be its first users.
