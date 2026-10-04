#!/usr/bin/env bash
# Live: headless `claude -p` answers, and a session can spawn an engine sub-agent.
#   ./tests/smoke-claude.sh            # uses CLAUDE_AUTH_MODE from .env
#   CLAUDE_AUTH_MODE=anthropic-api ./tests/smoke-claude.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")/.." && pwd)/scripts/docker-run.sh" smoke-agent "$@"
