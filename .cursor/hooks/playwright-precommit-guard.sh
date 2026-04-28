#!/usr/bin/env bash
set -euo pipefail

INPUT_JSON="$(cat)"

if ! command -v python3 >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

if ! command -v /usr/bin/docker >/dev/null 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: /usr/bin/docker is required for local Playwright checks.","agent_message":"Commit blocked by Playwright guard because /usr/bin/docker is unavailable."}
EOF
  exit 0
fi

if ! command -v bunx >/dev/null 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: bun/bunx is required. Install Bun and retry commit.","agent_message":"Commit blocked by Playwright guard because bunx is unavailable."}
EOF
  exit 0
fi

STAGED_FILES="$(git diff --cached --name-only)"
if [[ -z "${STAGED_FILES}" ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

if ! echo "${STAGED_FILES}" | python3 - <<'PY'
import re
import sys
text = sys.stdin.read()
patterns = [
    r"^frontend/tests/",
    r"^frontend/playwright\.config\.ts$",
    r"^frontend/Dockerfile\.playwright$",
    r"^\.github/workflows/playwright\.yml$",
]
for line in text.splitlines():
    if any(re.search(p, line) for p in patterns):
        sys.exit(0)
sys.exit(1)
PY
then
  echo '{"permission":"allow"}'
  exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

if [[ ! -f ".env.local" ]]; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: .env.local is missing. Create it before committing Playwright-related changes.","agent_message":"Commit blocked by Playwright guard because .env.local is missing."}
EOF
  exit 0
fi

if ! /usr/bin/docker compose --env-file .env.local up -d --wait backend >/tmp/playwright-guard-compose.log 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: could not start backend with docker compose. Check .env.local and docker logs, then retry.","agent_message":"Commit blocked by Playwright guard because docker compose backend startup failed."}
EOF
  exit 0
fi

if ! (
  export BUN_INSTALL="${HOME}/.bun"
  export PATH="${BUN_INSTALL}/bin:${PATH}"
  cd frontend
  bunx playwright test --fail-on-flaky-tests
) >/tmp/playwright-guard-test.log 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: local Playwright tests failed. Run `cd frontend && bunx playwright test --fail-on-flaky-tests` and fix failures before committing.","agent_message":"Commit blocked by Playwright guard because local Playwright tests failed."}
EOF
  exit 0
fi

echo '{"permission":"allow"}'
