#!/usr/bin/env bash
# Iteration 175 §9.2 — single entry that runs lint / typecheck / unit tests
# in Python workspace members and the frontend. Fail-fast (any step → exit non-zero).
#
# Hard wall-clock cap: 1800 seconds.
#
# Usage:
#   bash scripts/dev/check_all.sh
#   CHECK_ALL_ALLOW_MISSING=1 bash scripts/dev/check_all.sh   # docs-only hosts
#
# Exit codes:
#   0   — all members green
#   1   — one or more steps failed; stderr names the failing step / member.
#   2   — a required tool is missing (fail closed; no silent skip).
#   124 — overall timeout exceeded.

set -uo pipefail

BUDGET_SECONDS=1800
START=$(date +%s)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MEMBERS=("src/backend" "src/bt_api_py")
FRONTEND_MEMBER="src/frontend"
ALLOW_MISSING="${CHECK_ALL_ALLOW_MISSING:-0}"

require_tool() {
  local tool="$1"
  local member="$2"
  if command -v "$tool" > /dev/null 2>&1; then
    return 0
  fi
  if [ "$ALLOW_MISSING" = "1" ]; then
    echo "WARN: $tool not in PATH — skipping $member checks (explicitly allowed)" >&2
    return 1
  fi
  echo "::error::required tool '$tool' is not in PATH for $member" >&2
  echo "Install it or set CHECK_ALL_ALLOW_MISSING=1 for a docs-only run." >&2
  exit 2
}

# Best-effort detection of mypy strict scope per member.
detect_mypy_scope() {
  local member="$1"
  local pyproject="$member/pyproject.toml"
  if [ -f "$pyproject" ]; then
    # Default to scanning the standard backend `app/` directory if present;
    # otherwise scan the package directory matching the member basename
    # (e.g. `bt_api_py/`).
    if [ -d "$member/app" ]; then
      echo "app"
    elif [ -d "$member/$(basename "$member")" ]; then
      echo "$(basename "$member")"
    else
      # Fall back to the member root as a last resort.
      echo "."
    fi
  else
    echo "."
  fi
}

elapsed() {
  echo $(( $(date +%s) - START ))
}

over_budget() {
  local e
  e=$(elapsed)
  if [ "$e" -ge "$BUDGET_SECONDS" ]; then
    echo "::error::check_all.sh exceeded ${BUDGET_SECONDS}s budget (elapsed=${e}s)" >&2
    exit 124
  fi
}

run_step() {
  local member="$1"
  local label="$2"
  shift 2
  echo "::group::[$member] $label"
  if ! ( cd "$member" && "$@" ); then
    echo "::endgroup::"
    echo "::error::check_all.sh failed step '$label' in $member" >&2
    exit 1
  fi
  echo "::endgroup::"
  over_budget
}

for member in "${MEMBERS[@]}"; do
  if [ ! -d "$REPO_ROOT/$member" ]; then
    echo "WARN: workspace member missing on disk: $member — skipping" >&2
    continue
  fi

  if require_tool ruff "$member"; then
    run_step "$member" "ruff check" ruff check .
    run_step "$member" "ruff format --check" ruff format --check .
  fi

  if require_tool mypy "$member"; then
    scope=$(detect_mypy_scope "$member")
    run_step "$member" "mypy $scope" mypy "$scope"
  fi

  if require_tool pytest "$member"; then
    run_step "$member" 'pytest -m "not e2e"' pytest -m "not e2e" -q
  fi
done

if [ -d "$REPO_ROOT/$FRONTEND_MEMBER" ]; then
  if require_tool npm "$FRONTEND_MEMBER"; then
    if [ ! -d "$REPO_ROOT/$FRONTEND_MEMBER/node_modules" ]; then
      run_step "$FRONTEND_MEMBER" "npm ci" npm ci
    fi
    run_step "$FRONTEND_MEMBER" "npm run lint" npm run lint
    run_step "$FRONTEND_MEMBER" "npm run typecheck" npm run typecheck
    run_step "$FRONTEND_MEMBER" "npm run test -- --run" npm run test -- --run
  fi
fi

echo "OK: check_all.sh — all members green ($(elapsed)s)"
