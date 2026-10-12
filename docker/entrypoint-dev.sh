#!/bin/bash
set -e

echo "=== ai-for-investor Backend Dev Entrypoint ==="

# Probe using the configured async URL and its actual DBAPI driver. A missing
# driver is a configuration error, while connection failures are retried.
MAX_RETRIES=30
RETRY_INTERVAL=2
RETRIES=0

echo "Waiting for database to be ready..."
while [ $RETRIES -lt $MAX_RETRIES ]; do
    if python - <<'PY'
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.exc import NoSuchModuleError

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("DATABASE_URL is required for the configured database readiness probe", file=sys.stderr)
    sys.exit(2)

try:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
except (ImportError, ModuleNotFoundError, NoSuchModuleError) as exc:
    print(f"Required database driver is unavailable for DATABASE_URL: {exc}", file=sys.stderr)
    sys.exit(2)

async def probe() -> None:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

try:
    asyncio.run(probe())
except (ImportError, ModuleNotFoundError, NoSuchModuleError) as exc:
    print(f"Required database driver is unavailable for DATABASE_URL: {exc}", file=sys.stderr)
    sys.exit(2)
except Exception as exc:
    print(f"Database connection is not ready: {exc}", file=sys.stderr)
    sys.exit(1)

print("Database is ready (async SELECT 1).")
PY
    then
        PROBE_STATUS=0
    else
        PROBE_STATUS=$?
    fi
    if [ "$PROBE_STATUS" -eq 0 ]; then
        break
    fi
    if [ "$PROBE_STATUS" -eq 2 ]; then
        exit 2
    fi
    RETRIES=$((RETRIES + 1))
    echo "  Retry $RETRIES/$MAX_RETRIES - waiting ${RETRY_INTERVAL}s..."
    sleep $RETRY_INTERVAL
done

if [ "$RETRIES" -eq "$MAX_RETRIES" ]; then
    echo "ERROR: Database not ready after $((MAX_RETRIES * RETRY_INTERVAL))s" >&2
    exit 1
fi

# Run seed data script if enabled
if [ "${SEED_DATA:-false}" = "true" ]; then
    echo "SEED_DATA=true: Checking if seed data is needed..."
    if [ -f "/opt/workspace/ai-for-investor/scripts/seed_dev_data.py" ]; then
        python /opt/workspace/ai-for-investor/scripts/seed_dev_data.py || \
            echo "WARNING: Seed data script failed, continuing anyway..."
    else
        echo "INFO: Seed script not found, skipping. (Will be available after task 5.5)"
    fi
fi

echo "=== Starting application ==="
exec "$@"
