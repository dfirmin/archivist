# 0008 — A second harness: Pi, behind a harness interface

Status: proposed, 2026-10-07. Scoping document; becomes accepted when the live proof below
passes on both example targets.

## Why

A document takes 7–10 minutes through the full pipeline. Pi (`@earendil-works/pi-coding-agent`,
1.0.4, MIT) runs the same models through a far thinner harness: a few hundred tokens of system
prompt, four default tools, no permission layer, no TUI in headless mode. The hypothesis is that
most of the per-turn overhead Archivist pays today is harness, not engine: every Claude Code
sub-agent — fifteen Haiku gap-agents per concept among them — starts with Claude Code's own
system prompt and full tool schemas before it sees the engine's prompt. The goal is faster runs
at the same quality, and a harness interface so a third harness (Codex) is an adapter, not a
rewrite. OpenCode was looked at and set aside: more tokens per turn and more CPU than Pi.

What this ADR does **not** change: contracts, agents' prompts as judgement, skills, the run
plan, record-gap, the write fence, publishing. Quality lives in those, and the same model reads
the same prompt on either harness. The only harness behaviours the engine's quality rests on are
sub-agent isolation (a stage starts with no memory of the conductor), skill preloading
(`skills:` on an agent) and the tool allowlist; each is reproduced below.

## What the engine takes from Claude Code today

Read from the code, not the docs. This is the whole adapter surface.

| # | Coupling | Where |
|---|---|---|
| 1 | `claude -p --agent conductor --output-format stream-json --verbose --model … --permission-mode bypassPermissions`, kickoff on stdin | `claude_runner.build_claude_argv`, `launch_claude` |
| 2 | Agents installed as `.claude/agents/<name>.md` (name, description, model, `tools`, `skills` preload); the conductor's tool list rewritten to `Agent(<roster>)` | `agents.render_agent`, `with_roster`, `write_agent_definitions` |
| 3 | Skills copied to `.claude/skills/` for discovery; run plan at `.claude/archivist/run-plan.yaml` | `skills.install_skills`, `run_plan` |
| 4 | Stream parsing: `system.init` (agents loaded → abort if the roster is missing, session id, model, skill count); `assistant` blocks with a `Task`/`Agent` tool_use carrying `subagent_type`, `description`, `prompt`; `parent_tool_use_id` to label sub-agent output; `user` tool_result keyed by tool_use_id → the dispatch's result text; `result` with `is_error`, `num_turns`, `total_cost_usd` | `stream.StreamMonitor` |
| 5 | Dispatch check and loop control read dispatch *results* as text (planner `Groups:` regex, held documents, entry stage ran) | `dispatch_check`, `run_conductor_agent` |
| 6 | Transcripts grouped by `parent_tool_use_id`, one file per sub-agent | `transcripts.TranscriptRecorder` |
| 7 | Auth via env for the `claude` process: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`; `apiKeyHelper` in `settings.json` for `local-claude`; `inherit` | `config.resolve_auth`, `docker/entrypoint.sh` |
| 8 | Claude Code tool names in prompts: `Agent`, `Skill`, `TodoWrite`, `Glob` (and `Read/Write/Edit/Bash/Grep`, which Pi has as lowercase); `.claude/` in paths and in the git-skill's unstaged list | `agents/*.md`, five skills |
| 9 | Smoke: `claude -p` then a supervisor that spawns the `smoke` agent | `run_smoke_agent` |
| 10 | Docker image installs `@anthropic-ai/claude-code@2.1.159` | `Dockerfile` |

Everything else in `src/archivist/` (contracts, profile, roster, run plan, scope, fence,
record-gap, prune-gaps, requeue, check-concept, workspace, publishing) never touches the harness.

## Pi, as verified on 2026-10-07 (repo `earendil-works/pi` @ eb326d2)

- Headless: `pi --mode json -p --no-session` emits JSONL (`session` header with id → `agent_start`,
  `tool_execution_start/end` with `toolCallId`, `toolName`, `args`, `result`, `isError`,
  `message_update` with cumulative `usage` incl. `cost`, `message_end` as the final message,
  `agent_end`, `compaction_start/end`). Piped stdin is prepended to the first prompt. **JSON mode
  does not set a non-zero exit code for a failed response**; the final message's `stopReason`
  (`error`/`aborted`) is the signal.
- `--system-prompt <text|path>` replaces the default prompt; `--append-system-prompt` repeatable.
  `--model`, `--provider`, `--thinking`, `-t/--tools <allowlist>`, `-nc` (no AGENTS.md/CLAUDE.md).
- Agent dir `~/.pi/agent` (override `PI_CODING_AGENT_DIR`): `extensions/`, `skills/`, `agents/`,
  `models.json`, `settings.json`. Project `.pi/` is trust-gated and skipped headless unless
  `--approve`; the agent dir is not gated.
- Skills: Agent Skills spec (`SKILL.md`), discovered from the agent dir, **on demand only**
  (name + description in the system prompt; the model reads the file). No preload frontmatter.
- **No built-in sub-agent tool** (by design). The repo ships `examples/extensions/subagent/`: a
  tool that spawns one `pi --mode json -p --no-session --model … --tools … --system-prompt
  <tmpfile>` process per agent, with single / parallel (array of tasks in one call) / chain modes,
  and returns each final message as the tool result. The SDK's `createAgentSession(…)` gives an
  in-process nested session as the alternative.
- Extensions: `export default function (pi: ExtensionAPI)`, `pi.registerTool({name, description,
  parameters, execute})`, hooks `tool_call` (can block), `before_agent_start`,
  `before_provider_headers`, `session_start`, `agent_end`…; TypeScript loaded at runtime (jiti),
  no build; load with `-e <path>` or from the agent dir; active in JSON mode.
- Providers: Anthropic via `ANTHROPIC_API_KEY`, `ANTHROPIC_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`.
  **No `ANTHROPIC_BASE_URL`**; a gateway is a custom provider in `models.json`
  (`api: anthropic-messages | openai-completions | …`, `baseUrl`, `apiKey: "$ENV"` or
  `"!command"`, a `models` list with context window and max output).
- Tools: `read, bash, edit, write, grep, find, ls` (default-enabled: the first four). No `Glob`
  (`find` is it), no `TodoWrite`, no `Skill` tool. Auto-compaction on (reserve 16k, keep 20k).
- No permission prompts; gating is an extension's job. Docker stays the boundary.

## Decision (proposed)

1. **A harness is an adapter behind one interface.** `src/archivist/harness/` gains a
   `Harness` protocol with four duties — `install(workspace, engine, roster)`, `argv(model,
   agent | system_prompt)`, `monitor(required_agents) -> StreamMonitor-like`, `smoke()` — and
   two implementations, `claude_code` (today's code, moved) and `pi`. `claude_runner.py`
   becomes `runner.py` and calls the harness; the run loop, dispatch check, fence, transcripts
   interface and kickoff are untouched. Selection: `ARCHIVIST_HARNESS=claude-code|pi` (default
   `claude-code`), also `--harness` on `run-conductor` and `smoke`. The monitor interface the
   loop depends on is small: `dispatches`, `results`, `dispatched_agents`, `final_text`,
   `saw_result`, `is_error`, `abort_reason`, `session_id`, `write_transcripts`.

2. **The engine installs into a private Pi agent dir, never into the target.** `install`
   writes `<workspace>/.archivist/pi/{extensions,skills,agents,models.json,settings.json}` and
   the run sets `PI_CODING_AGENT_DIR` to it. Nothing trust-gated, nothing from the operator's
   `~/.pi` leaks in, and the bundle gains no `.pi/`. The run plan moves to a harness-neutral
   `.archivist/run-plan.yaml`; `.claude/archivist/run-plan.yaml` stays as a symlink on the
   Claude Code harness for one release, and the knowledge-repo-git skill's unstaged list gains
   `.archivist/`. Runs pass `-nc`: engine agents get everything from the kickoff, the plan and
   skills, as they do today (Claude Code loads `CLAUDE.md`, which bundles do not carry).

3. **One extension, `archivist-agent`, is the sub-agent tool.** ~300–400 lines of TypeScript,
   engine-owned (`harness/pi/extension/index.ts`), copied into the agent dir on install. It
   registers a tool named `Agent` with Claude Code's schema (`subagent_type`, `description`,
   `prompt`) plus an optional `tasks: [...]` list, so `conductor.md` and every `dispatch` rule in
   `profile.yaml` read the same on both harnesses. Per spawn it:
   - refuses a `subagent_type` outside the run plan's roster (the `Agent(<roster>)` allowlist,
     now enforced in code rather than by the harness);
   - reads `<agent dir>/agents/<name>.md` (name, description, model, tools, skills), builds the
     system prompt as the agent body **with every preloaded `skills:` body appended** — this is
     what reproduces Claude Code's preload, which Pi lacks — and maps tool names
     (`Read→read, Write→write, Edit→edit, Bash→bash, Grep→grep, Glob→find`, plus `ls`);
   - spawns `pi --mode json -p --no-session --model <m> -nc -t <tools> --system-prompt <file>`
     with the prompt on stdin, the run's env, cwd the workspace — the pattern the repo's own
     example uses; `tasks` run concurrently with `Promise.all` (bounded by
     `ARCHIVIST_PI_CONCURRENCY`, default the fleet size);
   - writes the child's JSONL to `out/transcripts/<session>/<description>.jsonl` as it streams,
     prints `[dispatch] <agent> — <description>` and `[dispatch] <agent> returned|failed` to
     stderr, and returns the child's final text (capped) as the tool result, `isError` when the
     child's `stopReason` is `error`/`aborted` or it exits non-zero.
   It also registers `Skill` (returns a skill's `SKILL.md` from the agent dir; the enricher and
   extractor load method skills on demand) and strips pre-release beta headers in
   `before_provider_headers` when the auth mode says so (today's
   `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`). `TodoWrite` is not reproduced: the conductor keeps
   its group checklist in its own text, a three-line prompt edit.

4. **The Pi stream monitor is a second parser of the same shape.** `PiStreamMonitor` maps
   `session` → session id; `tool_execution_start` with `toolName == "Agent"` → a `Dispatch`
   (one per task when `tasks` is used, ids `<toolCallId>#<i>`); `tool_execution_end` → that
   dispatch's result text (so `planner_gave_up`, `first_group_documents` and
   `check_entry_stage_ran` work unchanged); `message_update.usage` → cost; `message_end` →
   `final_text`, `saw_result`, `is_error` from `stopReason`; `agent_end` → done. The roster-loaded
   check (`system.init` today) becomes a deterministic pre-launch check that every roster agent
   file is in the agent dir, which is stronger than reading it back from the stream.
   Transcripts: the conductor's JSONL from the monitor, each sub-agent's from the extension;
   `TranscriptRecorder` gains a "file already written by the child" entry type.

5. **Auth is `models.json`, generated from `resolve_auth`.** No new auth variables; the four
   modes map as:
   - `anthropic-api` → Pi's built-in `anthropic` provider, `ANTHROPIC_API_KEY` in env;
   - `gateway-key` → provider `archivist-gateway` `{api: anthropic-messages, baseUrl:
     <LITELLM_API_BASE>, apiKey: "$ANTHROPIC_API_KEY", models: [<LITELLM_MODEL …>]}` and
     `--provider archivist-gateway`; the model entry needs a context window and max-output
     figure the engine fills from a small table keyed on model family;
   - `local-claude` → the same provider with `apiKey: "!<apiKeyHelper path>"` (Pi's command
     form of the `apiKeyHelper`);
   - `inherit` → Pi's own `auth.json` / `ANTHROPIC_OAUTH_TOKEN`, untouched.
   `entrypoint.sh` writes nothing for Pi; the Python install step writes `models.json` per run.

6. **Prompts go harness-neutral where a name leaks.** Five skills and three agents say `Glob`;
   the conductor says `TodoWrite` and `.claude/…`. These become "search for files" and the
   new plan path. The agent `tools:` frontmatter keeps Claude Code's names (the renderer maps
   them per harness; the authoring guide gains the table). `Agent` and `Skill` stay, because
   the extension provides both under those names.

7. **Docker ships both.** The image pins `@earendil-works/pi-coding-agent@1.0.4` next to
   Claude Code; `ARCHIVIST_HARNESS` picks one at run time; the smoke command runs both when
   both are installed. Nothing in `docker-compose*.yml` changes.

## Where the speed comes from, and what to expect

Per sub-agent turn, Claude Code sends its own system prompt and ~15 tool schemas ahead of the
engine's prompt; Pi sends a few hundred tokens and 4–6 schemas. The author and conductor
sessions are long enough that this is mostly cache reads (cheap, fast), but every *new* sub-agent
process pays the cache write once, and the gap fleet starts fifteen of them per concept. The
expected gains, in order: fewer input tokens per turn (cost), shorter time-to-first-token per
turn (wall clock), and no permission or hook plumbing between tool calls. What does not change:
the number of model turns, the reading the author does, and model latency — the bulk of the
7–10 minutes. A realistic target is a 20–40 % wall-clock reduction and a larger token
reduction; anything claimed beyond that is measured, not assumed. The live proof records both.

CPU: one `pi` process per sub-agent means the gap fleet is fifteen Node processes at once
(roughly 80–120 MB each), against Claude Code's in-process sub-agents. If peak CPU or memory is
the problem on the runner, the extension switches to `createAgentSession` in-process (same
tool, same contract, one process); the subprocess form is chosen first because the repo
proves it and it isolates each stage's context as Claude Code does.

## Risks and open questions

| Risk | Handling |
|---|---|
| Pi may execute several tool calls in one assistant message sequentially | The `tasks` list runs the fleet concurrently inside one call regardless; the conductor's "spawn the whole fleet in one message" becomes "in one `Agent` call" on both harnesses |
| `!command` `apiKey` may be evaluated once per process, not per request; an expiring helper token could fail a long session in `local-claude` mode | Verify in the spike; if once-only, the extension refreshes it in `before_provider_headers` |
| Anthropic's terms for Claude-subscription OAuth through third-party harnesses (`inherit` / `local-claude` on a personal login) | Not an engine problem; `anthropic-api` and `gateway-key` (the enterprise paths) are unaffected. Document, do not work around |
| JSON mode exit code is 0 on a failed response | Monitor derives failure from `stopReason`; a test covers it |
| Gateway model ids need `models.json` metadata Pi cannot discover | Small family table in the engine; unknown family → explicit `ARCHIVIST_PI_CONTEXT_WINDOW` or a refusal naming it |
| Pi 1.0.x is young; extension API may move | Pinned in the Dockerfile like Claude Code; the extension depends on five API calls |
| Compaction in a long conductor session could summarise a dispatch result before the conductor acts on it | Same exposure as Claude Code; raise `reserveTokens` in the generated `settings.json`; the write fence and dispatch check catch the consequences |

## Deterministic steps added

- **Roster enforcement in the sub-agent tool** — replaces a harness feature (`Agent(<roster>)`)
  with a lookup against the run plan; no judgement.
- **Pre-launch roster check** — every roster agent file present in the agent dir; replaces
  reading `system.init`.
- **Skill preload by concatenation** — reproduces `skills:`; no judgement.

The extension is harness plumbing, not a pipeline step; agents keep every judgement they have.

## Effort

| Phase | Work | Size |
|---|---|---|
| 0 — spike | By hand, outside the engine: the extension's spawn path, one `author` run on `examples/minimal` via Pi with skills preloaded, JSONL parsed. Answers the `!command` and parallel-tool questions. | 1 day |
| 1 — engine | `harness/` package, move Claude Code code, `pi` harness (install, `models.json`, argv, monitor, transcripts), the extension, prompt edits, Dockerfile, CLI flag; offline tests: renderer per harness, `models.json` per auth mode, Pi stream parsing against a recorded fixture, roster refusal, `stopReason` → failure | 2–3 days |
| 2 — live proof | Both example targets, both harnesses, same inbox; the role table from AGENTS.md checked per harness; `anthropic-api` and `gateway-key` modes; a benchmark table (wall clock, input/output/cache tokens, cost, peak CPU and RSS) per stage | 1–2 days |

Roughly a week of focused work. Codex afterwards is a third `Harness` implementation (its
`exec` mode, AGENTS.md, a sub-agent story of its own) and inherits all of this.

## Live proof required

Per harness, on `examples/warehouse` and `examples/handbook`: a full inbox run (including a
transcript, so the extractor and the extract group dispatch are covered), a `--kind` gap run
on all concepts, a rescore, and a publishing run on `archivist-knowledge-01`. Pass when every
role in the AGENTS.md table holds on Pi as it does on Claude Code, placement outcomes and gap
verdicts agree across three repetitions, the fence never fires, and the benchmark table shows
the gain. Status moves to accepted on that evidence; the default harness stays `claude-code`
until a second release has run on Pi without a Pi-specific fix.
