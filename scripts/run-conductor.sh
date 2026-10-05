#!/usr/bin/env bash
# Run the conductor, the main agent, over a loaded target workspace.
#
# With no variables set the conductor takes the whole inbox and publishes.
#
#   ./scripts/run-conductor.sh                                    # whole inbox, publish
#   INBOX_LIMIT=1 ./scripts/run-conductor.sh                      # at most one inbox document
#   GROUP_LIMIT=10 ./scripts/run-conductor.sh                     # at most 10 groups (a session each)
#   INBOX_FILE=sources/inbox/foo.md ./scripts/run-conductor.sh
#   CONCEPT_FILE='knowledge/.../overview.md' ./scripts/run-conductor.sh   # existing concept
#   PIPELINE=gaps CONCEPTS=all ./scripts/run-conductor.sh          # re-judge every published concept
#   PIPELINE=gaps CONCEPTS=all KINDS=missing_escalation ./scripts/run-conductor.sh   # one kind, all concepts
#   PIPELINE=rescore CONCEPTS='knowledge/a.md,knowledge/b.md' ./scripts/run-conductor.sh
#   SKIP_PUBLISH=1 ./scripts/run-conductor.sh                     # no branch/commit/push/PR/issues
#   PIPELINE=author-verify ./scripts/run-conductor.sh             # only these stages run
#   ENGINE=v0.2.0 ./scripts/run-conductor.sh                      # try another engine once (pin unchanged)
#
# PIPELINE names a pipeline from contracts/target.yaml or agents/profile.yaml (default: the
# target's default_pipeline, else the engine's). With CONCEPT_FILE or CONCEPTS (comma-separated
# paths, or `all`) the producing stage drops out; KINDS (comma-separated gap kind ids) narrows the
# gap fleet; CONCEPT_BATCH sets concepts per session (default 10). See docs/adr/0004.
#
# TARGET_SLUG (default sample) picks the workspace under out/workspace/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p out/workspace

TARGET_SLUG="${TARGET_SLUG:-sample}"
WORKSPACE="${WORKSPACE:-/workspace/${TARGET_SLUG}}"
INBOX_FILE="${INBOX_FILE:-}"
CONCEPT_FILE="${CONCEPT_FILE:-}"
CONCEPTS="${CONCEPTS:-}"
KINDS="${KINDS:-}"
CONCEPT_BATCH="${CONCEPT_BATCH:-0}"
SKIP_PUBLISH="${SKIP_PUBLISH:-0}"
INBOX_LIMIT="${INBOX_LIMIT:-0}"
GROUP_LIMIT="${GROUP_LIMIT:-0}"
PIPELINE="${PIPELINE:-}"
ENGINE="${ENGINE:-}"

COMPOSE=(-f docker-compose.yml -f docker-compose.github.yml)
# Auth mode: the shell wins, then .env, then the default (gateway-key).
AUTH_MODE="${CLAUDE_AUTH_MODE:-}"
if [[ -z "$AUTH_MODE" && -f .env ]]; then
  AUTH_MODE="$(sed -n 's/^CLAUDE_AUTH_MODE=//p' .env | tr -d "\"'" | tail -1)"
fi
AUTH_MODE="${AUTH_MODE:-gateway-key}"
if [[ "$AUTH_MODE" == "local-claude" ]]; then
  COMPOSE+=(-f docker-compose.local-claude.yml)
fi

RUN_ARGS=(-e "CLAUDE_AUTH_MODE=${AUTH_MODE}")
if [[ -n "${RUN_BRANCH:-}" ]]; then
  RUN_ARGS+=(-e "RUN_BRANCH=${RUN_BRANCH}")
fi

ARGS=(archivist run-conductor "$WORKSPACE")
if [[ -n "${INBOX_FILE}" ]]; then
  ARGS+=(--inbox-file "$INBOX_FILE")
fi
if [[ "$INBOX_LIMIT" -gt 0 ]]; then
  ARGS+=(--inbox-limit "$INBOX_LIMIT")
fi
if [[ "$GROUP_LIMIT" -gt 0 ]]; then
  ARGS+=(--group-limit "$GROUP_LIMIT")
fi
if [[ -n "${CONCEPT_FILE}" ]]; then
  ARGS+=(--concept "$CONCEPT_FILE")
fi
if [[ -n "${CONCEPTS}" ]]; then
  ARGS+=(--concept "$CONCEPTS")
fi
if [[ -n "${KINDS}" ]]; then
  ARGS+=(--kind "$KINDS")
fi
if [[ "$CONCEPT_BATCH" -gt 0 ]]; then
  ARGS+=(--concept-batch "$CONCEPT_BATCH")
fi
if [[ -n "${PIPELINE}" ]]; then
  ARGS+=(--pipeline "$PIPELINE")
fi
if [[ -n "${ENGINE}" ]]; then
  ARGS+=(--engine "$ENGINE")
fi
if [[ "${CONTINUE_BRANCH:-0}" == "1" ]]; then
  ARGS+=(--continue-branch)
fi
if [[ "$SKIP_PUBLISH" == "1" ]]; then
  ARGS+=(--skip-publish)
fi

printf 'conductor %s\n' "${ARGS[*]}"

docker compose "${COMPOSE[@]}" build worker
# Bash 3.2 (macOS /bin/bash) treats "${empty[@]}" as unbound under `set -u`.
# ${arr[@]+"${arr[@]}"} expands to nothing when empty, and to the elements otherwise.
exec docker compose "${COMPOSE[@]}" run --rm ${RUN_ARGS[@]+"${RUN_ARGS[@]}"} worker "${ARGS[@]}"
