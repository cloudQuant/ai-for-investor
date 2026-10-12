#!/usr/bin/env bash
set -euo pipefail

if [[ "${RESTORE_ALLOW_DESTRUCTIVE:-}" != "YES" ]]; then
    echo "Set RESTORE_ALLOW_DESTRUCTIVE=YES to replace the configured application database." >&2
    exit 2
fi
if [[ $# -ne 1 || ! -f "$1" || ! -f "$1.sha256" ]]; then
    echo "Usage: RESTORE_ALLOW_DESTRUCTIVE=YES $0 <backup.sql.gz> (with matching .sha256)" >&2
    exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE_RELATIVE_PATH="${ENV_FILE_RELATIVE_PATH:-src/backend/.env}"
if [[ "$ENV_FILE_RELATIVE_PATH" = /* ]]; then
    ENV_FILE="$ENV_FILE_RELATIVE_PATH"
else
    ENV_FILE="$PROJECT_ROOT/$ENV_FILE_RELATIVE_PATH"
fi
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-docker/docker-compose.yml}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose/prod.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai-for-investor}"

compose_args=(--project-directory "$PROJECT_ROOT" --project-name "$COMPOSE_PROJECT_NAME")
if [[ -n "$ENV_FILE_RELATIVE_PATH" ]]; then
    compose_args+=(--env-file "$ENV_FILE")
fi
if [[ -n "$COMPOSE_BASE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_BASE_FILE")
fi
if [[ -n "$COMPOSE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_FILE")
fi

for service in backend frontend migrate; do
    services="$(docker compose "${compose_args[@]}" config --services)"
    if grep -Fxq "$service" <<< "$services"; then
        running="$(docker compose "${compose_args[@]}" ps --status running -q "$service")"
        if [[ -n "$running" ]]; then
            echo "Stop Compose service '$service' before restoring the database." >&2
            exit 3
        fi
    fi
done

backup_path="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
(
    cd "$(dirname "$backup_path")"
    sha256sum -c "$(basename "$backup_path").sha256"
)
if ! gzip -cd "$backup_path" | grep -F -- "-- Current Database:" >/dev/null; then
    echo "Backup does not contain a MySQL database dump." >&2
    exit 4
fi

database_name="$(awk -F= '$1 == "DB_NAME" { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE")"
if [[ ! "$database_name" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "DB_NAME must contain only letters, digits, and underscores for safe restore." >&2
    exit 4
fi
if ! gzip -cd "$backup_path" | grep -F -- "-- Current Database: \`$database_name\`" >/dev/null; then
    echo "Backup database does not match configured DB_NAME '$database_name'." >&2
    exit 4
fi

docker compose "${compose_args[@]}" exec -T -e "EXPECTED_DB_NAME=$database_name" mysql sh -ec \
    'case "$MYSQL_DATABASE" in ""|*[!A-Za-z0-9_]*) echo "Unsafe MYSQL_DATABASE" >&2; exit 4;; esac; test "$MYSQL_DATABASE" = "$EXPECTED_DB_NAME" || { echo "MYSQL_DATABASE does not match the configured DB_NAME" >&2; exit 4; }; export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; mysql --user=root -e "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"'
gzip -cd "$backup_path" | docker compose "${compose_args[@]}" exec -T mysql sh -ec \
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --user=root "$MYSQL_DATABASE"'

echo "Restored configured MySQL database from $backup_path"
