# 0008 — A second harness: Pi, behind a harness interface

Status: proposed, 2026-10-07. Implemented on `feat/pi-harness` and proven live for authoring,
extraction, gap and score runs on both test targets (docs/live-proof/2026-10-07.md). Becomes
accepted once publishing on Pi is proven live. The default harness stays `claude-code`.

## Why

A document takes 7–10 minutes through the full pipeline. Pi (`@earendil-works/pi-coding-agent`,
1.0.4, MIT) runs the same models through a far thinner harness: a few hundred tokens of system
prompt, a handful of tools, no permission layer. The hope was faster runs at the same quality,
and a harness interface so a third harness (Codex) is an adapter, not a rewrite. OpenCode was
looked at and set aside: more tokens per turn and more CPU than Pi.

**What the live runs found: Pi is as fast as Claude Code, not faster, and about half the cost.**
A full inbox (17 documents, 12 sessions) took 1,247 s on Pi and 1,250 s on Claude Code side by
side; Claude Code alone varied by 6 % between runs. The time is model turns, and the harness does
not change the turns. The cost falls because Pi sends a fraction of Claude Code's prompt and tool
schemas on every turn (cache reads 4.7 M against 12.8 M tokens for the same run). Quality matched
once Pi sent the same thinking settings as Claude Code (§4).

So Pi is worth having for cost and for portability (open source, model-agnostic, no Claude Code
client policy at a gateway), not for speed. Faster runs have to come from the engine: fewer or
cheaper turns per stage, a smaller gap fleet, more parallel groups.

What this ADR does **not** change: contracts, agents' prompts, skills, the run plan, record-gap,
the write fence, publishing. Quality lives in those, and the same model reads the same prompt on
either harness.

## What the engine takes from a harness

Read from the code. This is the whole adapter surface; everything else in `src/archivist/` never
touches the harness.

| # | Coupling | Claude Code | Pi |
|---|---|---|---|
| 1 | Headless session as an agent, kickoff on stdin | `claude -p --agent <name> --output-format stream-json` | `pi --mode json -p --no-session -nc --provider … --model … --tools … --append-system-prompt <prompt file>` |
| 2 | Agents and their roster | `.claude/agents/<name>.md`; the conductor's tools rewritten to `Agent(<roster>)` | `.claude/pi/agents/<name>.json` (model, Pi tool list, prompt file); the roster in `ARCHIVIST_PI_ROSTER`, enforced by the extension |
| 3 | Skills, preloaded and on demand | `.claude/skills/`; `skills:` preloads | `.claude/pi/skills/`, listed by Pi for on-demand reads; `skills:` bodies appended to the agent's prompt file; a `Skill` tool from the extension |
| 4 | Sub-agents | built in | the extension's `Agent` tool (below) |
| 5 | Stream parsing | `StreamMonitor` | `PiStreamMonitor`, same surface |
| 6 | Auth | env for `claude`, `settings.json` | a generated `models.json` per auth mode |
| 7 | Smoke | `claude -p`, then a supervisor spawning `smoke` | `pi -p`, then the same supervisor |

## Decision

1. **A harness is an adapter behind one interface** (`archivist.harness.Harness`): `install`,
   `session_env`, `argv`, `monitor`, `smoke_argv`. `ClaudeCodeHarness` is the original code, moved;
   `PiHarness` is new. `ARCHIVIST_HARNESS=claude-code|pi` chooses (default `claude-code`). It is an
   environment variable, not a flag, so it survives the hand-off to a target's pinned engine. The
   run loop, kickoff, dispatch check, fence and transcripts are unchanged and harness-blind.

2. **Pi's agent dir is private to the run**: `<workspace>/.claude/pi/`, pointed to by
   `PI_CODING_AGENT_DIR` for the session and every spawn. Nothing comes from the operator's
   `~/.pi` (except `auth.json` in `inherit` mode), nothing is trust-gated, `-nc` keeps context
   files out, and `.claude/` is already generated per run and never committed. The run plan stays
   at `.claude/archivist/run-plan.yaml`. No agent or skill prompt changed.

3. **One engine extension provides the Claude Code tools the prompts name** (`harness/pi/archivist.ts`,
   TypeScript loaded by Pi at runtime, no build):
   - `Agent` with Claude Code's parameters (`subagent_type`, `description`, `prompt`). It refuses
     an agent outside the roster, reads the agent's JSON, and runs it as a separate `pi` process
     (its own context, as a Claude Code sub-agent has) with the prompt on stdin. It writes the
     child's events to `.claude/pi/events/<call id>.jsonl` for the transcripts, prints the child's
     progress, and returns its final message with its usage. Pi runs the tool calls of one message
     concurrently, so "spawn the whole fleet in one message" holds unchanged (proven offline: two
     children in flight at once).
   - `Skill` returns a skill's `SKILL.md`; `TodoWrite` accepts the conductor's checklist.
   - It asks for thinking with `display: "omitted"`, as Claude Code does.

   Python resolves everything else at install time: the tool map (`Glob` is Pi's `find` and `ls`;
   an agent without `tools:` gets every tool but `Agent`), the prompt file with preloaded skills,
   the model. The extension decides nothing.

4. **Thinking as Claude Code sends it.** Requests captured live through a logging proxy:
   Claude Code sends Sonnet 5.5 `thinking: adaptive` at `effort: medium`, and Haiku 4.5 `thinking:
   enabled, budget_tokens: 31999`, both `display: omitted`. Pi's defaults differ (a fixed 8,192
   budget on every model), and the first parity guess, Haiku thinking off because Claude Code's
   transcripts show no thinking blocks, cost quality. Pi's Haiku gap-agents then got 22–24 of 30
   judgements right against Claude Code's 30; with the same settings, 59 of 60 over ten runs
   against Claude Code's 58 of 60. `pi_settings` and `provider_for` now set adaptive thinking
   (`compat.forceAdaptiveThinking`) for 5.x Sonnet, Opus and Fable models and a 31,999 budget for
   the rest. A replacement for Pi's coding-assistant preamble was tried in the same experiment and
   dropped: no measurable effect.

5. **`PiStreamMonitor`** reads Pi's JSON events into `StreamMonitor`'s surface: `session` → id;
   the first system message's `toolsAdded` must include `Agent` when the run needs sub-agents,
   or the session is aborted before it spends tokens (Claude Code's `init` check); `Agent`
   tool start/end → dispatches and result text, so the planner parsing and the entry-stage check
   are unchanged; assistant `stopReason` `error`/`aborted` → failure (Pi's JSON mode exits 0 on
   a failed response; proven live when the API key ran out of credit).

6. **Auth is `models.json`, generated from `resolve_auth`.** No new auth variables:
   - `anthropic-api` → Pi's built-in `anthropic` provider with `ANTHROPIC_API_KEY`;
   - `gateway-key` → provider `archivist-gateway` (`anthropic-messages`, the gateway URL,
     `apiKey: "$ANTHROPIC_API_KEY"`), every pinned model with its limits; pre-release betas off
     when `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` is set, as for Claude Code (proven live through
     a proxy);
   - `local-claude` → the same provider with `apiKey: "!<apiKeyHelper>"`, which Pi runs per
     request, so long sessions refresh their token as Claude Code's do;
   - `inherit` → Pi's own auth: `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` (as
     `ANTHROPIC_OAUTH_TOKEN`), or the operator's `~/.pi/agent/auth.json`. A Claude subscription
     login through a third-party harness draws from extra usage (the API refused it live without
     extra usage enabled); use `anthropic-api` or a gateway for Pi.

7. **The image ships both**: Pi pinned next to Claude Code, plus `fd-find` and `ripgrep`, which
   Pi's `find` and `grep` tools need and otherwise download on first use (a network allowlist
   blocks that; found live).

## Deterministic steps added

- **Roster enforcement in the extension's `Agent` tool**: a lookup against the run plan's roster,
  replacing a Claude Code feature (`Agent(<roster>)`); no judgement.
- **The `toolsAdded` check**: the extension loaded, replacing Claude Code's `init` check.
- **Skill preload by concatenation**: reproduces `skills:`; no judgement.

All three are harness plumbing; agents keep every judgement they had.

## Risks

| Risk | Handling |
|---|---|
| Pi 1.0.x is young; its extension API or event names may move | Pinned in the image like Claude Code; the extension uses five API calls; the offline tests run real `pi` processes and break on a change |
| Thinking defaults drift between harnesses again (a new model, a new Claude Code default) | `pi_settings`/`provider_for` are the one place; the logging-proxy comparison in the live proof is the way to re-check |
| Gateway models need metadata Pi cannot discover | A small family table (context window, output limit); thinking mode by model family |
| One `pi` process per sub-agent (about 130 MB each; a 4-kind fleet is 4 at once) | Measured fine on 2 CPUs / 7 GB. If memory binds, the extension can use Pi's SDK in-process instead; same tool, same contract |

## Live proof

docs/live-proof/2026-10-07.md. Proven: smoke, full inbox runs on both targets, extraction,
placement and quarantine, gap and score runs, `anthropic-api` and `gateway-key` modes, failure
detection. Outstanding: publishing on Pi (branch, PR, issues, re-run without duplicates) and
`local-claude` mode.
