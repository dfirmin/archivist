#!/usr/bin/env bash
# Cache-aware apiKeyHelper wrapper for CLAUDE_AUTH_MODE=local-claude.
#
# Claude Code calls this on every model request to fetch the API key. The
# enterprise SSO helper (REAL_HELPER) mints a fresh token each call: a Node
# cold start plus two SSO round-trips (OIDC discovery + refresh), even when a
# still-valid access token is already saved on disk. That per-call cost is the
# dominant slowdown for local-claude runs.
#
# This wrapper adds the token reuse the enterprise helper omits: if the saved
# access token is still valid (beyond a safety margin), print it directly with
# zero network and zero Node. Only when it is missing, unreadable, or near
# expiry do we exec REAL_HELPER to mint a new one.
#
# We deliberately do NOT edit the enterprise helper: it self-updates and would
# overwrite any change. This wrapper ships in our image instead.
set -euo pipefail

AUTH_DIR="${CLAUDE_CODE_AUTH_DIR:-$HOME/.claude-code-auth}"
TOKENS_FILE="$AUTH_DIR/tokens.json"
REAL_HELPER="${CLAUDE_REAL_API_KEY_HELPER:-$AUTH_DIR/bin/api_key_helper.sh}"
# Reuse the token until it is within this many seconds of expiry.
MARGIN_SECONDS="${CLAUDE_TOKEN_CACHE_MARGIN_SECONDS:-120}"

# Fast path: reuse the on-disk SSO access token while it is safely unexpired.
# python3 does the JSON read + expiry math; a non-zero exit means 'cannot reuse'
# (missing/corrupt/near-expiry) and we fall through to the real helper.
if [[ -r "$TOKENS_FILE" ]]; then
  if token="$(TOKENS_FILE="$TOKENS_FILE" MARGIN_SECONDS="$MARGIN_SECONDS" python3 - <<'PY'
import json, os, sys, time

try:
    with open(os.environ["TOKENS_FILE"], encoding="utf-8") as fh:
        data = json.load(fh)
    token = data["access_token"]
    expires_at = float(data["expires_at"])  # epoch seconds
except Exception:
    sys.exit(1)  # unusable cache -> let the caller mint a fresh token

margin = float(os.environ["MARGIN_SECONDS"])
if not token or time.time() + margin >= expires_at:
    sys.exit(1)  # empty or too close to expiry -> mint a fresh token

print(token)
PY
  )"; then
    printf '%s\n' "$token"
    exit 0
  fi
fi

# Slow path: mint/refresh via the operator's enterprise SSO helper.
exec "$REAL_HELPER"
