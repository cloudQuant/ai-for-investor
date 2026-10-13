#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE_RELATIVE_PATH="${ENV_FILE_RELATIVE_PATH:-src/backend/.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-docker/docker-compose.yml}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose/prod.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai-for-investor}"

docker compose \
    --project-directory "$PROJECT_ROOT" \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --env-file "$ENV_FILE_RELATIVE_PATH" \
    -f "$COMPOSE_BASE_FILE" \
    -f "$COMPOSE_FILE" \
    run --rm --no-deps --entrypoint python backend -m app.db.bootstrap_admin
