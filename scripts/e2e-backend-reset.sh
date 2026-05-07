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

bind_failure_hint() {
  echo "e2e-backend-reset: If Docker reported 'address already in use', free the stack's host ports (commonly 5432, 8000, 1080): run \`docker compose --env-file .env.local down\` for this project, remove stray containers, or stop a non-Docker service on that port, then run this script again." >&2
}

docker compose --env-file .env.local down -v --remove-orphans

# Build all Docker images before starting services.
docker compose --env-file .env.local build

# Mailcatcher is required for reset-password specs (recovery email).
if ! USER_REGISTRATION_ENABLED=true \
  docker compose --env-file .env.local up -d mailcatcher frontend; then
  bind_failure_hint
  exit 1
fi
# Playwright sign-up specs need the register API; locals often set this false in .env.local.
if ! USER_REGISTRATION_ENABLED=true \
  docker compose --env-file .env.local up -d --wait backend; then
  bind_failure_hint
  exit 1
fi

echo "e2e-backend-reset: waiting for Mailcatcher on http://127.0.0.1:1080/messages ..."
ready=
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:1080/messages" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ -z "${ready}" ]]; then
  echo "e2e-backend-reset: Mailcatcher did not respond in time (1080)." >&2
  exit 1
fi
echo "e2e-backend-reset: Mailcatcher is ready."
