#!/usr/bin/env bash
# ARIA AI — money-boundary smoke test inside the local docker-compose stack.
#
# Runs tests/integration/test_money_boundaries_smoke.py (the 3 money
# boundaries in sandbox mode: no real keys, no network charges) inside the
# api container built from the local Dockerfile.
#
# Usage: ./scripts/smoke_e2e_docker.sh
# Requires: docker + docker compose plugin, .env present (never committed).
set -euo pipefail

cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon is not reachable. Start docker and retry." >&2
  exit 1
fi

echo "==> building aria-api image (local Dockerfile)..."
docker compose -f infra/docker-compose.yml build aria-api

echo "==> running money-boundary smoke suite in sandbox mode..."
docker compose -f infra/docker-compose.yml run --rm \
  -e ENVIRONMENT=test \
  aria-api \
  python -m pytest tests/integration/test_money_boundaries_smoke.py \
                 tests/unit/test_llm_contracts.py \
                 tests/unit/test_dead_letter_store.py \
                 tests/unit/test_user_facing_contracts.py \
                 tests/unit/test_aria_site.py -q

echo "==> smoke test finished"
