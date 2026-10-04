#!/usr/bin/env bash
# Offline test suite, inside Docker. No credentials needed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "${DOCKER_CONTAINER:-}" == "1" ]]; then
  exec python -m pytest -q "$@"
fi
docker compose -f docker-compose.yml build worker
exec docker compose -f docker-compose.yml run --rm --entrypoint "" worker python -m pytest -q "$@"
