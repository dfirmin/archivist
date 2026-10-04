#!/usr/bin/env bash
# Live: headless `claude -p` answers, and a session can spawn an engine sub-agent.
#   CLAUDE_AUTH_MODE=local-claude ./tests/smoke-claude.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")/.." && pwd)/scripts/docker-run.sh" smoke-agent "$@"
