#!/usr/bin/env bash
set -euo pipefail

INPUT_JSON="$(cat)"
_unused="${INPUT_JSON}"

if ! command -v git >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Backend pytest guard: uv is required. Install uv and retry commit.","agent_message":"Commit blocked by backend pytest guard because uv is unavailable."}
EOF
  exit 0
fi

staged_files="$(git diff --cached --name-only)"
if [[ -z "${staged_files}" ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

needs_backend_gate=0
declare -A target_set=()

add_target_if_exists() {
  local target="$1"
  if [[ -f "${target}" ]]; then
    target_set["${target}"]=1
  fi
}

while IFS= read -r file; do
  [[ -z "${file}" ]] && continue
  case "${file}" in
    backend/tests/*.py)
      needs_backend_gate=1
      target_set["${file#backend/}"]=1
      ;;
    backend/app/api/routes/*.py)
      needs_backend_gate=1
      base="$(basename "${file}" .py)"
      add_target_if_exists "backend/tests/api/routes/test_${base}.py"
      add_target_if_exists "backend/tests/api/routes/test_${base}_unit.py"
      ;;
    backend/app/services/*.py)
      needs_backend_gate=1
      base="$(basename "${file}" .py)"
      add_target_if_exists "backend/tests/services/test_${base}.py"
      ;;
    backend/app/models.py|backend/app/models/*.py)
      needs_backend_gate=1
      add_target_if_exists "backend/tests/test_lesson_models.py"
      add_target_if_exists "backend/tests/test_initial_data.py"
      ;;
    backend/pyproject.toml|backend/alembic.ini|backend/app/main.py|backend/app/core/config.py)
      needs_backend_gate=1
      ;;
  esac
done <<< "${staged_files}"

if [[ "${needs_backend_gate}" -ne 1 ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}/backend"

pytest_args=(-q --tb=short)
if [[ "${#target_set[@]}" -gt 0 ]]; then
  while IFS= read -r target; do
    pytest_args+=("${target}")
  done < <(printf '%s\n' "${!target_set[@]}" | sort)
else
  pytest_args+=(tests/api/routes/test_private.py tests/api/routes/test_workshop_sessions.py tests/services/test_workshop_realtime.py)
fi

if ! uv run pytest "${pytest_args[@]}" >/tmp/backend-pytest-guard-test.log 2>&1; then
  cat <<'EOF'
{"permission":"ask","user_message":"Backend pytest guard: targeted backend tests failed. Run `cd backend && uv run pytest -q --tb=short <relevant tests>` and fix failures before committing.","agent_message":"Commit blocked by backend pytest guard because targeted backend tests failed."}
EOF
  exit 0
fi

echo '{"permission":"allow"}'
