#!/usr/bin/env bash
# Reset DB-backed services and bring backend up deterministically before E2E.
# Repo root — uses .env.local (same convention as playwright-precommit hook).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ ! -f .env.local ]]; then
  echo "e2e-backend-reset: .env.local missing in ${REPO_ROOT}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "e2e-backend-reset: docker is not installed or not on PATH" >&2
  exit 1
fi

docker compose --env-file .env.local down -v --remove-orphans
# Playwright sign-up specs need the register API; locals often set this false in .env.local.
USER_REGISTRATION_ENABLED=true \
  docker compose --env-file .env.local up -d --wait backend
