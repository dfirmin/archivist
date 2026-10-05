# Authoring agents and skills

How to write and change files in `agents/` and `skills/`. Read it before you add or edit
one. It follows Anthropic's skill-authoring guidance and its guidance for Claude 5 generation
models, adapted to this engine. What archivist's agents may do (agentic first, domain in
contracts) is in [AGENTS.md](../AGENTS.md); this page is about how the files are written.

Contents: 1 Before you write · 2 Frontmatter · 3 Body · 4 Wording by model · 5 One place per
instruction · 6 Grounding and evidence · 7 Commands, not prose · 8 Proving a change ·
9 Checklist · 10 Sources

## 1. Before you write

- **Prefer changing what exists.** A new behaviour is usually a contract field, a skill
  section or a dispatch rule, not a new agent ([AGENTS.md → Adding things](../AGENTS.md#adding-things)).
- **Start from a failure.** Write the smallest instruction that fixes something you saw in a
  live run or a transcript. An instruction with no failure behind it is a guess and costs
  tokens on every run.
- **Know who reads it.** An agent prompt is read by one model on every spawn. A skill is read
  by every agent that preloads it, or loaded on demand from its description. A contract is read
  by agents but written by target owners.

## 2. Frontmatter

| Field | Rule |
|---|---|
| `name` | Lowercase letters, numbers and hyphens, at most 64 characters, no `claude` or `anthropic`; equals the directory (skill) or file stem (agent). Python enforces it. |
| `description` | Third person, starting with a verb: "Judges one gap kind …", not "Judge …" or "I judge …". First what it does, then `Use when …`. At most 1024 characters, no XML tags. This is what an agent reads to decide whether to load a skill, so name the triggers concretely. |
| `model` (agents only) | A literal model id (`claude-sonnet-5-5`, `claude-haiku-4-5-20251001`), never a variable. Skills carry no model. |
| `tools` (agents) / `allowed-tools` (skills) | Only what the steps use. If a step tells the agent to write a file, the tool list includes Write. |
| `skills` (agents) | Preload a skill only if every run of the agent needs it; otherwise let the agent load it by description. |

## 3. Body

- **Numbered steps, each ending in Done when.** A step names its action in capitals (`READ`,
  `RECORD`), says what to do, and ends with a checkable `Done when …`. The final report shape
  comes last, in a code block.
- **Short.** Agents and skills here stay under about 110 lines; 500 is the hard ceiling;
  past that, split into files one level below `SKILL.md`, each linked directly from it.
- **A file over 100 lines opens with a one-line `Contents:` list**, because agents often read
  only the top of a long file.
- **Positive instructions, one term per concept.** Say what to do. Pick one word for a thing
  (`concept`, `cited source`, `reference contract`) and keep it across files.
- **Nothing that dates.** No "after release X" or "before October"; describe the current
  behaviour only.
- **Container paths.** `/workspace/…`, `/app/…`, `/tmp/…`, or paths relative to the
  knowledge-repo root. A host path is a defect.
- **No domain words.** No subject areas, teams, systems or business terms in an engine file;
  they belong in a target's contracts (AGENTS.md rule 4).

## 4. Wording by model

The same text behaves differently on different models. Write for the model the agent pins,
and check it on that model.

**Sonnet and Opus 5.x** (author, conductor, enricher, intake-planner, verifier) follow plain
wording literally and use judgement well:

- Give the goal and the principle behind a rule; let the model apply it. "Delete any detail
  no cited source states, whatever it came from" beats a list of typical cases.
- Name the tool when a step needs one: "write the file with the Write tool", "run
  `archivist check-concept`". These models do less of what is only implied.
- Leave out worked examples, long rule lists and shouted emphasis (MUST, NEVER, CRITICAL,
  ALWAYS, bold warnings). They over-constrain and can push the model into rigid or
  over-cautious behaviour.

**Haiku 4.5** (gap-agent, scorer) needs more structure:

- Explicit, ordered decision steps that stop at the first match (the origin steps in
  `skills/gap-kinds` are the model to copy).
- An example of the exact command to run, with real flags.
- A closed set of outputs (`present: true|false`, a named origin, `Score: <n>`).

When you change an agent's model, re-read its prompt for the new tier and adjust it in the
same change.

## 5. One place per instruction

- **Say each rule once, in the file that owns it.** A rule about sections lives in
  `document-structure`; the author points to "**document-structure** §3" instead of
  restating it. Two copies drift, and the model then has to choose between them.
- **No contradictions across layers.** An agent, its skills and a target's contracts are read
  together. When two of them disagree, fix the source rather than adding a tie-break. Example:
  a contract rule made gap origin `author` whenever reference data held a value, while the
  author skill forbids copying reference data into the body; origins flipped between runs until
  the contract rule was removed (issue #3).
- **Contracts are binding prose.** An engine file never overrides a target's `guidance`,
  `scope`, `from` or `structure_rule`; it explains how to read them.

## 6. Grounding and evidence

Every agent that writes concept text works from evidence it can point to:

- Body text restates a **cited source** document. Reference contracts supply frontmatter
  values and scope decisions only. Model knowledge supplies nothing.
- Missing information is an expected outcome. It takes the section's empty form (stub or
  omission) and becomes a gap downstream; an agent never completes a section from elsewhere.
- A judgement that assigns blame or routing quotes its evidence: an `author` gap origin quotes
  the source passage the concept dropped.
- Prefer a step whose output can be checked (an evidence file, a quoted passage, a count in
  the report) over an instruction to "be careful".

## 7. Commands, not prose

A fragile, must-be-exact operation is a command the agent runs, not a paragraph it follows:
`archivist record-gap` and `archivist prune-gaps` (YAML under a lock), `archivist
check-concept` (frontmatter against contracts). Add a new deterministic step only after a live failure shows an agent cannot be
made reliable, and record the decision in `docs/adr/` (AGENTS.md rule 2). Scripts handle
their own errors and print a specific message; the agent fixes what the message names.

## 8. Proving a change

Offline tests do not prove a prompt. A change to an agent or skill is done when it has run
live and you have read the output ([testing.md](testing.md), AGENTS.md → Live proof):

- Run it on the model the agent pins, on at least two targets when it touches the author,
  the conductor or a contract kind, with messy and clean source documents.
- For a judgement (gap presence, origin, structure choice), repeat it at least three times
  on unchanged inputs and record whether the answers agree.
- Read the transcripts under `out/transcripts/` for anything that surprised you: unexpected
  file reads, skipped steps, ignored sections. They show where a file is unclear.
- Record the runs, costs and what you checked in `docs/live-proof/`.

## 9. Checklist

Before you open the pull request:

- [ ] `name` and `description` follow §2; the description is third person with `Use when …`
- [ ] Steps are numbered and each ends in **Done when**; the report shape is last
- [ ] Under 500 lines; a `Contents:` line when over 100
- [ ] Wording fits the pinned model (§4); no shouted emphasis on 5.x agents
- [ ] No rule restated from a skill or contract; no contradiction with them (§5)
- [ ] No domain words, dates or host paths
- [ ] Writing steps ground text in cited sources (§6)
- [ ] `python -m pytest -q` passes (it parses every agent and skill)
- [ ] Live proof recorded (§8)

## 10. Sources

- [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
  (Anthropic)
- [The new rules of context engineering for Claude 5 generation models](https://claude.dev/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models/)
  (Anthropic)
- [Migrating to Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
  (Anthropic)
