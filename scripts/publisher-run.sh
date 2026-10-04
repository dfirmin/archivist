#!/usr/bin/env bash
# Trusted Git/GitHub ops (load-target, prepare-target) on the worker with publisher mode.
# Uses the same GitHub overlay as run-conductor.sh; sets ARCHIVIST_PUBLISHER=1
# so those commands are allowed. Agent conductor sessions do not set that flag.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p out/workspace

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <archivist-args...>" >&2
  echo "example: $0 prepare-target --target sample /workspace/sample" >&2
  echo "example: $0 load-target --target sample /workspace/sample" >&2
  exit 1
fi

COMPOSE=(-f docker-compose.yml -f docker-compose.github.yml)

docker compose "${COMPOSE[@]}" build worker
exec docker compose "${COMPOSE[@]}" run --rm \
  -e ARCHIVIST_PUBLISHER=1 \
  worker archivist "$@"
