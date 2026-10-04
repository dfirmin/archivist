#!/usr/bin/env bash
# Run archivist CLI commands inside the worker container.
#
#   ./scripts/docker-run.sh config-check
#   ./scripts/docker-run.sh smoke-agent      # claude -p + sub-agent spawn
#
# Auth comes from CLAUDE_AUTH_MODE (shell, else .env). For example:
#   CLAUDE_AUTH_MODE=anthropic-api ./scripts/docker-run.sh smoke-agent
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
# Auth mode: the shell wins, then .env, then the default (gateway-key).
AUTH_MODE="${CLAUDE_AUTH_MODE:-}"
if [[ -z "$AUTH_MODE" && -f .env ]]; then
  AUTH_MODE="$(sed -n 's/^CLAUDE_AUTH_MODE=//p' .env | tr -d "\"'" | tail -1)"
fi
AUTH_MODE="${AUTH_MODE:-gateway-key}"
if [[ "$AUTH_MODE" == "local-claude" ]]; then
  COMPOSE+=(-f docker-compose.local-claude.yml)
fi

docker compose "${COMPOSE[@]}" build worker
exec docker compose "${COMPOSE[@]}" run --rm -e "CLAUDE_AUTH_MODE=${AUTH_MODE}" worker archivist "$@"
