#!/usr/bin/env bash
# Check the entry chunk and the complete /login first-load closure from Vite's
# manifest. Dynamic imports are reported separately and do not enter either
# first-load budget.

set -euo pipefail

DIST_DIR="${1:-src/frontend/dist}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTE_ASSETS_HELPER="$SCRIPT_DIR/list_route_assets.mjs"

# Existing hard budgets from Iteration 175. The login count now includes every
# initial JS chunk, including vendor chunks, instead of hiding vendor requests.
ENTRY_GZIP_BUDGET_BYTES=307200
ENTRY_INITIAL_JS_BUDGET=4
LOGIN_INITIAL_JS_BUDGET=4
INITIAL_CLOSURE_GZIP_BUDGET_BYTES=$((640 * 1024))
SINGLE_INITIAL_JS_GZIP_BUDGET_BYTES=$((540 * 1024))

# Existing advisory thresholds (uncompressed).
MAX_TOTAL_KB=20000
MAX_VENDOR_CHUNK_KB=8000

echo "=========================================="
echo "Frontend Bundle Size Check (manifest based)"
echo "=========================================="

if [ ! -d "$DIST_DIR" ]; then
  echo "ERROR: dist directory not found at $DIST_DIR"
  echo "Run 'npm run build' first."
  exit 1
fi
if [ ! -f "$ROUTE_ASSETS_HELPER" ]; then
  echo "ERROR: route asset helper not found at $ROUTE_ASSETS_HELPER"
  exit 1
fi

# The helper fails closed when the manifest, route key, or referenced asset is
# missing or malformed. Keep the complete report as the only source of inputs.
ASSET_REPORT="$(node "$ROUTE_ASSETS_HELPER" /login "$DIST_DIR" --format=json)"

report_value() {
  node -e 'const report = JSON.parse(process.argv[1]); const value = report[process.argv[2]]; if (Array.isArray(value)) process.stdout.write(value.join("\n")); else if (typeof value === "string") process.stdout.write(value); else throw new Error(`missing report field ${process.argv[2]}`)' "$ASSET_REPORT" "$1"
}

ENTRY_FILE="$(report_value entryFile)"
ENTRY_INITIAL_FILES="$(report_value entryInitialFiles)"
ENTRY_INITIAL_JS_FILES="$(report_value entryInitialJsFiles)"
LOGIN_INITIAL_FILES="$(report_value initialFiles)"
LOGIN_INITIAL_JS_FILES="$(report_value initialJsFiles)"
LOGIN_DELAYED_FILES="$(report_value delayedFiles)"
LOGIN_DELAYED_JS_FILES="$(report_value delayedJsFiles)"
INITIAL_JS_FILES="$(printf '%s\n%s\n' "$ENTRY_INITIAL_JS_FILES" "$LOGIN_INITIAL_JS_FILES" | awk 'NF && !seen[$0]++')"

# Portable stat (BSD vs GNU).
filesize() {
  local file="$1"
  stat -f%z "$file" 2>/dev/null || stat --format=%s "$file" 2>/dev/null
}

asset_count() {
  local list="$1"
  awk 'NF { count += 1 } END { print count + 0 }' <<< "$list"
}

javascript_count() {
  local list="$1"
  awk 'NF && /\.(c|m)?js$/ { count += 1 } END { print count + 0 }' <<< "$list"
}

sum_sizes() {
  local list="$1"
  local mode="$2"
  local total=0 relative_file absolute_file size
  while IFS= read -r relative_file; do
    [ -n "$relative_file" ] || continue
    absolute_file="$DIST_DIR/$relative_file"
    if [ ! -f "$absolute_file" ]; then
      echo "ERROR: manifest asset is missing at gate time: $relative_file" >&2
      return 1
    fi
    if [ "$mode" = "gzip" ]; then
      size="$(gzip -c -9 "$absolute_file" | wc -c | tr -d '[:space:]')"
    else
      size="$(filesize "$absolute_file")"
    fi
    total=$((total + size))
  done <<< "$list"
  printf '%s' "$total"
}

max_gzip_size() {
  local list="$1"
  local max_size=0 max_file="" relative_file absolute_file size
  while IFS= read -r relative_file; do
    [ -n "$relative_file" ] || continue
    absolute_file="$DIST_DIR/$relative_file"
    if [ ! -f "$absolute_file" ]; then
      echo "ERROR: manifest asset is missing at gate time: $relative_file" >&2
      return 1
    fi
    size="$(gzip -c -9 "$absolute_file" | wc -c | tr -d '[:space:]')"
    if [ "$size" -gt "$max_size" ]; then
      max_size="$size"
      max_file="$relative_file"
    fi
  done <<< "$list"
  printf '%s|%s' "$max_size" "$max_file"
}

ENTRY_RAW_BYTES="$(filesize "$DIST_DIR/$ENTRY_FILE")"
ENTRY_GZIP_BYTES="$(gzip -c -9 "$DIST_DIR/$ENTRY_FILE" | wc -c | tr -d '[:space:]')"
ENTRY_INITIAL_COUNT="$(asset_count "$ENTRY_INITIAL_FILES")"
ENTRY_INITIAL_JS_COUNT="$(asset_count "$ENTRY_INITIAL_JS_FILES")"
ENTRY_INITIAL_RAW="$(sum_sizes "$ENTRY_INITIAL_FILES" raw)"
ENTRY_INITIAL_GZIP="$(sum_sizes "$ENTRY_INITIAL_FILES" gzip)"
LOGIN_INITIAL_COUNT="$(asset_count "$LOGIN_INITIAL_JS_FILES")"
LOGIN_INITIAL_ASSET_COUNT="$(asset_count "$LOGIN_INITIAL_FILES")"
LOGIN_INITIAL_RAW="$(sum_sizes "$LOGIN_INITIAL_FILES" raw)"
LOGIN_INITIAL_GZIP="$(sum_sizes "$LOGIN_INITIAL_FILES" gzip)"
LOGIN_DELAYED_COUNT="$(asset_count "$LOGIN_DELAYED_JS_FILES")"
LOGIN_DELAYED_ASSET_COUNT="$(asset_count "$LOGIN_DELAYED_FILES")"
LOGIN_DELAYED_RAW="$(sum_sizes "$LOGIN_DELAYED_FILES" raw)"
LOGIN_DELAYED_GZIP="$(sum_sizes "$LOGIN_DELAYED_FILES" gzip)"
MAX_INITIAL_JS_INFO="$(max_gzip_size "$INITIAL_JS_FILES")"
MAX_INITIAL_JS_GZIP="${MAX_INITIAL_JS_INFO%%|*}"
MAX_INITIAL_JS_FILE="${MAX_INITIAL_JS_INFO#*|}"

# Existing advisory totals still include every built JS/CSS file, vendor or not.
TOTAL_BYTES=0
LARGEST_BYTES=0
while IFS= read -r -d '' asset_file; do
  asset_bytes="$(filesize "$asset_file")"
  TOTAL_BYTES=$((TOTAL_BYTES + asset_bytes))
  if [ "$asset_bytes" -gt "$LARGEST_BYTES" ]; then
    LARGEST_BYTES=$asset_bytes
  fi
done < <(find "$DIST_DIR" -type f \( -name '*.js' -o -name '*.css' \) -print0)
TOTAL_KB=$((TOTAL_BYTES / 1024))
LARGEST_KB=$((LARGEST_BYTES / 1024))

STATUS=PASS
print_row() {
  local name="$1" target="$2" actual="$3" pass="$4"
  printf '  %-42s | target=%-12s | actual=%-16s | %s\n' "$name" "$target" "$actual" "$pass"
}

echo ""
echo "--- Hard Budgets ---"
if [ "$ENTRY_GZIP_BYTES" -le "$ENTRY_GZIP_BUDGET_BYTES" ]; then
  print_row 'entry chunk gzip bytes' "<= $ENTRY_GZIP_BUDGET_BYTES" "$ENTRY_GZIP_BYTES" PASS
else
  print_row 'entry chunk gzip bytes' "<= $ENTRY_GZIP_BUDGET_BYTES" "$ENTRY_GZIP_BYTES" '[FAIL]'
  echo "::error::entry chunk gzip $ENTRY_GZIP_BYTES bytes > $ENTRY_GZIP_BUDGET_BYTES bytes (300 KB)"
  STATUS=FAIL
fi

if [ "$ENTRY_INITIAL_JS_COUNT" -le "$ENTRY_INITIAL_JS_BUDGET" ]; then
  print_row 'entry static initial JS chunks (all)' "<= $ENTRY_INITIAL_JS_BUDGET" "$ENTRY_INITIAL_JS_COUNT" PASS
else
  print_row 'entry static initial JS chunks (all)' "<= $ENTRY_INITIAL_JS_BUDGET" "$ENTRY_INITIAL_JS_COUNT" '[FAIL]'
  echo "::error::entry static initial JS chunks = $ENTRY_INITIAL_JS_COUNT > $ENTRY_INITIAL_JS_BUDGET"
  STATUS=FAIL
fi

if [ "$LOGIN_INITIAL_COUNT" -le "$LOGIN_INITIAL_JS_BUDGET" ]; then
  print_row '/login initial JS chunks (all)' "<= $LOGIN_INITIAL_JS_BUDGET" "$LOGIN_INITIAL_COUNT" PASS
else
  print_row '/login initial JS chunks (all)' "<= $LOGIN_INITIAL_JS_BUDGET" "$LOGIN_INITIAL_COUNT" '[FAIL]'
  echo "::error::/login initial JS chunks = $LOGIN_INITIAL_COUNT > $LOGIN_INITIAL_JS_BUDGET"
  STATUS=FAIL
fi

if [ "$ENTRY_INITIAL_GZIP" -le "$INITIAL_CLOSURE_GZIP_BUDGET_BYTES" ]; then
  print_row 'entry static closure gzip-9 bytes' "<= $INITIAL_CLOSURE_GZIP_BUDGET_BYTES" "$ENTRY_INITIAL_GZIP" PASS
else
  print_row 'entry static closure gzip-9 bytes' "<= $INITIAL_CLOSURE_GZIP_BUDGET_BYTES" "$ENTRY_INITIAL_GZIP" '[FAIL]'
  echo "::error::entry static closure gzip $ENTRY_INITIAL_GZIP bytes > $INITIAL_CLOSURE_GZIP_BUDGET_BYTES bytes (640 KiB)"
  STATUS=FAIL
fi

if [ "$LOGIN_INITIAL_GZIP" -le "$INITIAL_CLOSURE_GZIP_BUDGET_BYTES" ]; then
  print_row '/login initial closure gzip-9 bytes' "<= $INITIAL_CLOSURE_GZIP_BUDGET_BYTES" "$LOGIN_INITIAL_GZIP" PASS
else
  print_row '/login initial closure gzip-9 bytes' "<= $INITIAL_CLOSURE_GZIP_BUDGET_BYTES" "$LOGIN_INITIAL_GZIP" '[FAIL]'
  echo "::error::/login initial closure gzip $LOGIN_INITIAL_GZIP bytes > $INITIAL_CLOSURE_GZIP_BUDGET_BYTES bytes (640 KiB)"
  STATUS=FAIL
fi

if [ "$MAX_INITIAL_JS_GZIP" -le "$SINGLE_INITIAL_JS_GZIP_BUDGET_BYTES" ]; then
  print_row 'largest initial JS gzip-9 bytes' "<= $SINGLE_INITIAL_JS_GZIP_BUDGET_BYTES" "$MAX_INITIAL_JS_GZIP ($MAX_INITIAL_JS_FILE)" PASS
else
  print_row 'largest initial JS gzip-9 bytes' "<= $SINGLE_INITIAL_JS_GZIP_BUDGET_BYTES" "$MAX_INITIAL_JS_GZIP ($MAX_INITIAL_JS_FILE)" '[FAIL]'
  echo "::error::initial JS gzip $MAX_INITIAL_JS_GZIP bytes > $SINGLE_INITIAL_JS_GZIP_BUDGET_BYTES bytes (540 KiB): $MAX_INITIAL_JS_FILE"
  STATUS=FAIL
fi

echo ""
echo "--- Manifest Closures (gzip-9, raw bytes) ---"
printf '  entry static closure: %s total assets (%s JS), %s raw bytes, %s gzip bytes\n' "$ENTRY_INITIAL_COUNT" "$ENTRY_INITIAL_JS_COUNT" "$ENTRY_INITIAL_RAW" "$ENTRY_INITIAL_GZIP"
printf '  /login initial closure: %s total assets (%s JS), %s raw bytes, %s gzip bytes\n' "$LOGIN_INITIAL_ASSET_COUNT" "$LOGIN_INITIAL_COUNT" "$LOGIN_INITIAL_RAW" "$LOGIN_INITIAL_GZIP"
printf '  /login delayed closure: %s total assets (%s JS), %s raw bytes, %s gzip bytes\n' "$LOGIN_DELAYED_ASSET_COUNT" "$LOGIN_DELAYED_COUNT" "$LOGIN_DELAYED_RAW" "$LOGIN_DELAYED_GZIP"

print_asset_list() {
  local label="$1" list="$2" relative_file
  printf '  %s\n' "$label"
  while IFS= read -r relative_file; do
    [ -n "$relative_file" ] || continue
    printf '    %s\n' "$relative_file"
  done <<< "$list"
}

print_asset_list 'entry initial JS files (all)' "$ENTRY_INITIAL_JS_FILES"
print_asset_list '/login initial JS files (all)' "$LOGIN_INITIAL_JS_FILES"

echo ""
echo "--- Advisory Totals ---"
if [ "$TOTAL_KB" -gt "$MAX_TOTAL_KB" ]; then
  echo "::warning::Total ${TOTAL_KB}KB exceeds advisory ${MAX_TOTAL_KB}KB"
else
  echo "  total JS+CSS: ${TOTAL_KB} KB (advisory <= ${MAX_TOTAL_KB})"
fi
if [ "$LARGEST_KB" -gt "$MAX_VENDOR_CHUNK_KB" ]; then
  echo "::warning::Largest JS/CSS chunk ${LARGEST_KB}KB exceeds advisory ${MAX_VENDOR_CHUNK_KB}KB"
else
  echo "  largest JS/CSS chunk: ${LARGEST_KB} KB (advisory <= ${MAX_VENDOR_CHUNK_KB})"
fi

echo ""
echo "=========================================="
if [ "$STATUS" = FAIL ]; then
  echo '❌ Bundle size check FAILED'
  exit 1
fi
echo '✅ Bundle size check PASSED'
printf '  entry %s: raw %s bytes / gzip %s bytes\n' "$ENTRY_FILE" "$ENTRY_RAW_BYTES" "$ENTRY_GZIP_BYTES"
exit 0
