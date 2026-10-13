#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE_RELATIVE_PATH="${ENV_FILE_RELATIVE_PATH:-src/backend/.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-docker/docker-compose.yml}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose/prod.yml}"
COMPOSE_EXTRA_FILE="${COMPOSE_EXTRA_FILE:-}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai-for-investor}"
if [[ "$ENV_FILE_RELATIVE_PATH" = /* ]]; then
    ENV_FILE="$ENV_FILE_RELATIVE_PATH"
else
    ENV_FILE="$PROJECT_ROOT/$ENV_FILE_RELATIVE_PATH"
fi
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Deployment env file not found: $ENV_FILE" >&2
    exit 2
fi

compose_args=(--project-directory "$PROJECT_ROOT" --project-name "$COMPOSE_PROJECT_NAME" --env-file "$ENV_FILE")
if [[ -n "$COMPOSE_BASE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_BASE_FILE")
fi
if [[ -n "$COMPOSE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_FILE")
fi
if [[ -n "$COMPOSE_EXTRA_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_EXTRA_FILE")
fi

echo "Checking certificate renewal using the deployment's configured Certbot lineage."
if docker compose "${compose_args[@]}" run --rm --no-deps --entrypoint certbot certbot \
    renew --webroot --webroot-path /var/www/certbot; then
    :
else
    status=$?
    echo "Certificate renewal failed with exit status $status." >&2
    exit "$status"
fi
