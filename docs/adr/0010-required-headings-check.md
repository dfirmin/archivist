# 0010 — `check-concept` enforces the headings a structure requires

Status: accepted, 2026-10-07.

## Live failure

A structure lists a concept's sections; **document-structure** §3 says which the author must
write: every required author section (stubbed `*[Awaiting source material.]*` when no source
supports it) and every placeholder section. On the warehouse mirror, authors dropped the required
`## Business Rules & Usage Notes` from view overviews in 3 of 8 full runs on both harnesses
(Claude Code: 2 of 3 overviews in one run, 2 of 3 in another; Pi: 1 of 3), where other runs and
the baseline kept it. The gap fleet recorded each as `missing_section`, so the gap was reported,
but the concept broke its structure, and the issue asked people to fix what the engine should not
have dropped.

Every case was the same heading. Its only subsection, `Implementation Logic`, is optional and
holds an enricher section, and §3 said "a heading whose only children are enricher sections is
written by the enricher": authors stretched that to the grandparent.

## Decision

1. `archivist check-concept` lists every required heading that is missing, at its level (`##` for
   a section, `###` for a subsection), as §3 defines them: required author sections and
   placeholder sections, recursing into subsections; never an optional section or anything under
   it, never an enricher section, never a heading whose every direct subsection is an enricher
   section. Headings inside code blocks do not count. Whether a section has content stays a
   judgement for the gap fleet (`missing_section`).
2. The author already fixes everything `check-concept` lists before it is done, so a dropped
   heading is written in the same step. The verifier and enricher run the same check.
3. `check-concept --frontmatter` skips the body for stages that may change only frontmatter: the
   scorer uses it, so a rescore of an older concept missing a heading is not stuck on a body it
   may not edit.
4. §3 now says it plainly: only direct subsections count; a required section whose subsection is
   optional is the author's.

## Proof

Offline: one test per behaviour (missing, optional, level, code block, frontmatter-only, the
nested view-group case, placeholder and enricher sections). Against the 13 runs of 2026-10-07
(both targets, both harnesses, 125 concepts and drafts): exactly the 5 dropped headings found by
hand, nothing else. Live: docs/live-proof/2026-10-07.md.
