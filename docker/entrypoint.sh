#!/usr/bin/env bash
# Container entrypoint — wire Claude Code auth per CLAUDE_AUTH_MODE.
#
#   gateway-key (default): borrowed/static LITELLM_API_KEY -> ANTHROPIC_API_KEY,
#                          container-local settings.json (no apiKeyHelper).
#   local-claude:          defer to the operator's own Claude Code auth — a mounted
#                          ~/.claude-code-auth apiKeyHelper (enterprise SSO -> LiteLLM).
set -euo pipefail

# Target clones live on the /workspace bind mount, whose files carry the host
# owner rather than the container user, so git refuses them as dubious ownership.
git config --global --add safe.directory '/workspace/*'

# Pipeline commits must not depend on host git identity or the conductor inventing
# one. Defaults match archivist.workspace.ENGINE_GIT_NAME / ENGINE_GIT_EMAIL.
ENGINE_GIT_NAME="${GIT_AUTHOR_NAME:-Archivist}"
ENGINE_GIT_EMAIL="${GIT_AUTHOR_EMAIL:-archivist@noreply.local}"
export GIT_AUTHOR_NAME="$ENGINE_GIT_NAME"
export GIT_AUTHOR_EMAIL="$ENGINE_GIT_EMAIL"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$ENGINE_GIT_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$ENGINE_GIT_EMAIL}"
git config --global user.name "$ENGINE_GIT_NAME"
git config --global user.email "$ENGINE_GIT_EMAIL"

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh auth setup-git
fi

if [[ "${ARCHIVIST_PUBLISHER:-}" == "1" ]]; then
  exec "$@"
fi

AUTH_MODE="${CLAUDE_AUTH_MODE:-gateway-key}"

if [[ -n "${ACT_CLAUDE_MODEL:-}" ]]; then
  export ACT_CLAUDE_MODEL="${ACT_CLAUDE_MODEL%\"}"
  export ACT_CLAUDE_MODEL="${ACT_CLAUDE_MODEL#\"}"
  export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-$ACT_CLAUDE_MODEL}"
fi

export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS:-1}"
export DOCKER_CONTAINER="${DOCKER_CONTAINER:-1}"

CLAUDE_DIR="${HOME}/.claude"
mkdir -p "$CLAUDE_DIR"

if [[ "$AUTH_MODE" == "local-claude" ]]; then
  # Authenticate from the operator's own Claude Code login. Claude Code invokes the
  # local apiKeyHelper itself whenever it needs a token, so credentials refresh
  # during long-running sessions.
  # Do not export a startup token: it expires while the conductor is running.
  unset ANTHROPIC_API_KEY || true
  REAL_HELPER="${CLAUDE_LOCAL_API_KEY_HELPER:-$HOME/.claude-code-auth/bin/api_key_helper.sh}"
  if [[ ! -x "$REAL_HELPER" ]]; then
    echo "ERROR: CLAUDE_AUTH_MODE=local-claude but apiKeyHelper is missing/not executable:" >&2
    echo "         $REAL_HELPER" >&2
    echo "       Mount your host ~/.claude-code-auth into the container — run via:" >&2
    echo "         CLAUDE_AUTH_MODE=local-claude ./scripts/docker-run.sh <command>" >&2
    echo "       (docker-compose.local-claude.yml provides the bind mount)." >&2
    exit 1
  fi
  # Base URL comes from the settings.json env block (mirrors the host enterprise
  # install); prefer ANTHROPIC_BASE_URL, then LITELLM_API_BASE.
  export CLAUDE_REAL_API_KEY_HELPER="$REAL_HELPER"
  BASE_URL="${ANTHROPIC_BASE_URL:-${LITELLM_API_BASE:-}}"
  MODEL="${ACT_CLAUDE_MODEL:-${ANTHROPIC_MODEL:-}}"
  REAL_HELPER="$REAL_HELPER" BASE_URL="$BASE_URL" MODEL="$MODEL" python3 -c "
import json, os
settings = {
    'permissions': {'allow': [], 'deny': []},
    'apiKeyHelper': os.environ['REAL_HELPER'],
}
env = {
    'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1',
    'ENABLE_TOOL_SEARCH': 'false',
}
if os.environ.get('BASE_URL'):
    env['ANTHROPIC_BASE_URL'] = os.environ['BASE_URL']
settings['env'] = env
model = os.environ.get('MODEL')
if model:
    settings['model'] = model
with open(os.path.join(os.environ['HOME'], '.claude', 'settings.json'), 'w') as f:
    json.dump(settings, f, indent=2)
"
else
  # gateway-key (default) — existing behavior.
  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    export ANTHROPIC_API_KEY="${LITELLM_API_KEY:-}"
  fi
  if [[ -z "${ANTHROPIC_BASE_URL:-}" ]] && [[ -n "${LITELLM_API_BASE:-}" ]]; then
    export ANTHROPIC_BASE_URL="${LITELLM_API_BASE}"
  fi
  python3 -c "
import json, os
settings = {'permissions': {'allow': [], 'deny': []}}
model = os.environ.get('ACT_CLAUDE_MODEL') or os.environ.get('ANTHROPIC_MODEL', '')
if model:
    settings['model'] = model
with open(os.path.join(os.environ['HOME'], '.claude', 'settings.json'), 'w') as f:
    json.dump(settings, f, indent=2)
"
fi

exec "$@"
