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

needs_playwright_gate=0
needs_full_playwright_run=0
spec_files=()

while IFS= read -r file; do
  [[ -z "${file}" ]] && continue
  case "${file}" in
    frontend/tests/*.spec.ts)
      needs_playwright_gate=1
      spec_files+=("${file#frontend/}")
      ;;
    frontend/tests/*)
      needs_playwright_gate=1
      needs_full_playwright_run=1
      ;;
    frontend/playwright.config.ts|frontend/Dockerfile.playwright|.github/workflows/playwright.yml)
      needs_playwright_gate=1
      needs_full_playwright_run=1
      ;;
  esac
done <<< "${STAGED_FILES}"

if [[ "${needs_playwright_gate}" -ne 1 ]]; then
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

playwright_args=(--fail-on-flaky-tests --project=chromium)
if [[ "${needs_full_playwright_run}" -ne 1 && ${#spec_files[@]} -gt 0 ]]; then
  playwright_args+=("${spec_files[@]}")
fi

if ! (
  export BUN_INSTALL="${HOME}/.bun"
  export PATH="${BUN_INSTALL}/bin:${PATH}"
  cd frontend
  bunx playwright test "${playwright_args[@]}"
) >/tmp/playwright-guard-test.log 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Playwright guard: local Playwright tests failed. Run `cd frontend && bunx playwright test --project=chromium --fail-on-flaky-tests` (or the touched spec files) and fix failures before committing.","agent_message":"Commit blocked by Playwright guard because local Playwright tests failed."}
EOF
  exit 0
fi

echo '{"permission":"allow"}'
