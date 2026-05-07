#!/usr/bin/env bash
set -euo pipefail

INPUT_JSON="$(cat)"

if ! command -v git >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo '{"permission":"allow"}'
  exit 0
fi

current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "${current_branch}" ]]; then
  echo '{"permission":"allow"}'
  exit 0
fi

event_command="$(
python3 - <<'PY' "${INPUT_JSON}"
import json
import sys

raw = sys.argv[1]
try:
    data = json.loads(raw) if raw else {}
except Exception:
    data = {}
print(data.get("command", ""))
PY
)"

is_protected_branch=0
if [[ "${current_branch}" == "main" || "${current_branch}" == "master" ]]; then
  is_protected_branch=1
fi

is_invalid_scope_branch=0
if [[ "${current_branch}" != "main" && "${current_branch}" != "master" ]]; then
  if [[ ! "${current_branch}" =~ ^(feat|fix|chore|docs|test|refactor)/[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$ ]]; then
    is_invalid_scope_branch=1
  fi
  slice_slug="${current_branch##*/}"
  if [[ "${slice_slug}" =~ (^|-)next($|-) || "${slice_slug}" =~ (^|-)functionality($|-) || "${slice_slug}" =~ (^|-)slice($|-) || "${slice_slug}" =~ (^|-)misc($|-) || "${slice_slug}" =~ (^|-)temp($|-) || "${slice_slug}" =~ (^|-)wip($|-) || "${slice_slug}" =~ (^|-)changes($|-) ]]; then
    is_invalid_scope_branch=1
  fi
  if [[ "${current_branch}" == *"+"* || "${current_branch}" == *","* || "${current_branch}" == *"_and_"* || "${current_branch}" == *"-and-"* ]]; then
    is_invalid_scope_branch=1
  fi
fi

if [[ "${is_protected_branch}" -eq 1 ]]; then
  case "${event_command}" in
    git\ commit*|git\ push*|gh\ pr\ create*)
      if [[ "${ALLOW_MAIN_GIT_WORKFLOW:-0}" != "1" ]]; then
        cat <<'EOF'
{"permission":"ask","user_message":"Branch/PR guard: current branch is main/master. Create or switch to a feature branch before commit/push/PR create. Set ALLOW_MAIN_GIT_WORKFLOW=1 only for explicitly approved direct-to-main work.","agent_message":"Blocked by branch/PR guard: commit/push/PR-create attempted from protected branch."}
EOF
        exit 0
      fi
      ;;
  esac
fi

case "${event_command}" in
  git\ commit*|git\ push*|gh\ pr\ create*)
    if [[ "${is_invalid_scope_branch}" -eq 1 && "${ALLOW_MULTI_SCOPE_BRANCH:-0}" != "1" ]]; then
      cat <<'EOF'
{"permission":"ask","user_message":"Branch scope guard: use a specific single-slice branch name formatted as <type>/<scope>/<slice-slug> (e.g., feat/workshop/repo-health-filter). Generic slugs like next/functionality/slice or ambiguous multi-scope names are blocked.","agent_message":"Blocked by branch scope guard: branch name is generic or not a valid single-slice scope branch."}
EOF
      exit 0
    fi
    ;;
esac

echo '{"permission":"allow"}'
