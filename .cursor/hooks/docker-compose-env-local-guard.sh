#!/usr/bin/env bash
set -euo pipefail

INPUT_JSON="$(cat)"

if ! command -v python3 >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

COMMAND="$(
  printf '%s' "${INPUT_JSON}" | python3 -c 'import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(payload.get("command", ""))'
)"

# Only gate docker compose lifecycle commands.
if [[ ! "${COMMAND}" =~ ^docker[[:space:]]+compose[[:space:]]+ ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

if [[ "${COMMAND}" =~ [[:space:]]--env-file[[:space:]]+\.env\.local([[:space:]]|$) ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

cat <<'EOF'
{"permission":"deny","user_message":"Use `.env.local` for Docker Compose commands in this repo. Re-run with `docker compose --env-file .env.local ...`.","agent_message":"Blocked docker compose command because it did not include `--env-file .env.local`."}
EOF
exit 0
