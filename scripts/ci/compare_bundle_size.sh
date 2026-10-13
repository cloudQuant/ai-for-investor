#!/usr/bin/env bash
# CI script: compare the Vite manifest entry gzip size against the target branch.
#
# Iteration 175 §7.6 — > 10% growth blocks the PR. base missing → emit a
# notice and skip. The blocking can be bypassed by either:
#
#   - PR label `BUNDLE_SIZE_GROWTH_OVERRIDE`
#   - PR description containing `<!-- bundle-size-override: <reason> -->`
#
# An override additionally requires CODEOWNERS approval (advisory check —
# the actual approval enforcement happens in branch protection rules).
#
# Usage:
#   ./scripts/ci/compare_bundle_size.sh <current_dist_dir> <base_entry_gzip_bytes>
#
# Exit codes:
#   0 - within budget OR base missing OR override active
#   1 - growth > 10% AND no valid override

set -euo pipefail

CURRENT_DIST="${1:-src/frontend/dist}"
BASE_GZIP_BYTES="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GROWTH_THRESHOLD_NUM=10

ENTRY_REL="$(node "$SCRIPT_DIR/list_route_assets.mjs" /login "$CURRENT_DIST" --kind=entry-file)"
if [ -z "$ENTRY_REL" ]; then
  echo "ERROR: Vite manifest did not identify an entry file" >&2
  exit 1
fi
CURRENT_BYTES="$(gzip -n -c -9 "$CURRENT_DIST/$ENTRY_REL" | wc -c | tr -d '[:space:]')"

if [ -z "$BASE_GZIP_BYTES" ]; then
  echo "::notice::bundle-size base missing, ratchet skipped"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Bundle Size Ratchet"
      echo ""
      echo "_skipped — base entry chunk gzip size unavailable (target branch artifact missing)_"
    } >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi
if ! [[ "$BASE_GZIP_BYTES" =~ ^[0-9]+$ ]]; then
  echo "ERROR: base entry gzip size must be a non-negative integer" >&2
  exit 1
fi
if [ "$BASE_GZIP_BYTES" -eq 0 ]; then
  echo "::notice::bundle-size base = 0, ratchet skipped"
  exit 0
fi

DELTA=$((CURRENT_BYTES - BASE_GZIP_BYTES))
GROWTH_PCT="$(awk -v delta="$DELTA" -v base="$BASE_GZIP_BYTES" 'BEGIN { printf "%.3f", (delta * 100) / base }')"

echo "Current entry gzip: $CURRENT_BYTES bytes"
echo "Base entry gzip:    $BASE_GZIP_BYTES bytes"
echo "Delta:              $DELTA bytes (~ ${GROWTH_PCT}%)"

if [ "$DELTA" -le 0 ] || [ $((DELTA * 100)) -le $((BASE_GZIP_BYTES * GROWTH_THRESHOLD_NUM)) ]; then
  echo "::notice::Bundle size growth ${GROWTH_PCT}% within ratchet (<= ${GROWTH_THRESHOLD_NUM}%)"
  exit 0
fi

# Growth exceeds threshold — check overrides.
OVERRIDE_REASON=""
if [ -n "${PR_LABELS:-}" ] && echo "$PR_LABELS" | grep -q "BUNDLE_SIZE_GROWTH_OVERRIDE"; then
  OVERRIDE_REASON="label:BUNDLE_SIZE_GROWTH_OVERRIDE"
fi
if [ -n "${PR_BODY:-}" ]; then
  REASON_FROM_BODY=$(printf '%s' "$PR_BODY" | grep -oE '<!--[[:space:]]*bundle-size-override:[[:space:]]*[^>]+-->' | head -1 || true)
  if [ -n "$REASON_FROM_BODY" ]; then
    OVERRIDE_REASON="${OVERRIDE_REASON:+$OVERRIDE_REASON; }body:$REASON_FROM_BODY"
  fi
fi

if [ -n "$OVERRIDE_REASON" ]; then
  echo "::warning::bundle-size growth ${GROWTH_PCT}% exceeds ${GROWTH_THRESHOLD_NUM}% threshold but override active: $OVERRIDE_REASON"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Bundle Size Ratchet"
      echo ""
      echo "⚠️ growth=${GROWTH_PCT}% exceeds threshold but override is active: \`${OVERRIDE_REASON}\`"
      echo ""
      echo "Reminder: PR must additionally have a CODEOWNERS approval before merge."
    } >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi

echo "::error::Bundle size growth ${GROWTH_PCT}% exceeds ${GROWTH_THRESHOLD_NUM}% threshold (no override active)"
echo "Apply label \`BUNDLE_SIZE_GROWTH_OVERRIDE\` or include \`<!-- bundle-size-override: <reason> -->\` in PR description if growth is intentional."
exit 1
