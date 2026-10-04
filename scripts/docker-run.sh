#!/usr/bin/env bash
# Run archivist CLI commands inside the worker container.
#
#   ./scripts/docker-run.sh config-check
#   ./scripts/docker-run.sh smoke-agent      # claude -p + sub-agent spawn
#
# Opt-in: run agents through your own Claude Code access (see README):
#   CLAUDE_AUTH_MODE=local-claude ./scripts/docker-run.sh smoke-agent
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p out/workspace

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <archivist-args...>" >&2
  echo "example: $0 config-check" >&2
  exit 1
fi

COMPOSE=(-f docker-compose.yml)
if [[ "${CLAUDE_AUTH_MODE:-}" == "local-claude" ]]; then
  COMPOSE+=(-f docker-compose.local-claude.yml)
fi

docker compose "${COMPOSE[@]}" build worker
exec docker compose "${COMPOSE[@]}" run --rm worker archivist "$@"
