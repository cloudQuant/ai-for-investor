#!/usr/bin/env bash
# generate_lockfiles.sh - Generate pinned dependency lockfiles for reproducible builds.
#
# Usage:
#   ./scripts/ops/generate_lockfiles.sh
#
# The backend dependency source is src/backend/pyproject.toml. This script writes
# the canonical lockfiles under config/:
#   - config/requirements-dev.lock  (dev + selected optional deps)
#   - config/requirements-prod.lock (production + selected optional deps)
#
# Run from any directory after changing src/backend/pyproject.toml.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/src/backend"
CONFIG_DIR="$PROJECT_ROOT/config"
UV_BIN="${UV_BIN:-uv}"

echo "=== Generating dependency lockfiles ==="
echo "Backend directory: $BACKEND_DIR"
echo "Lockfile directory: $CONFIG_DIR"

if [[ ! -f "$BACKEND_DIR/pyproject.toml" ]]; then
    echo "Error: Backend pyproject.toml not found: $BACKEND_DIR/pyproject.toml" >&2
    exit 1
fi
if [[ ! -d "$CONFIG_DIR" ]]; then
    echo "Error: Canonical lockfile directory not found: $CONFIG_DIR" >&2
    exit 1
fi
if ! command -v "$UV_BIN" >/dev/null 2>&1; then
    echo "Error: uv executable not found: $UV_BIN" >&2
    exit 127
fi

# --- Generate requirements-dev.lock ---
echo ""
echo "--- Generating requirements-dev.lock (dev + backtrader/data/redis) ---"
(
    cd "$BACKEND_DIR"
    "$UV_BIN" pip compile pyproject.toml \
        --extra dev \
        --extra backtrader \
        --extra data \
        --extra redis \
        --no-emit-package pip \
        -o ../../config/requirements-dev.lock \
        --python-version 3.11 \
        --no-sources
)
echo "✓ Generated $CONFIG_DIR/requirements-dev.lock"

# --- Generate requirements-prod.lock ---
echo ""
echo "--- Generating requirements-prod.lock (prod + postgres/mysql/redis/backtrader/data) ---"
(
    cd "$BACKEND_DIR"
    "$UV_BIN" pip compile pyproject.toml \
        --extra prod \
        --extra postgres \
        --extra mysql \
        --extra redis \
        --extra backtrader \
        --extra data \
        -o ../../config/requirements-prod.lock \
        --python-version 3.11 \
        --no-sources
)
echo "✓ Generated $CONFIG_DIR/requirements-prod.lock"

echo ""
echo "=== Done. Canonical lockfiles written under config/ ==="
echo "  - $CONFIG_DIR/requirements-dev.lock"
echo "  - $CONFIG_DIR/requirements-prod.lock"
echo ""
echo "Commit these files to ensure reproducible builds."
