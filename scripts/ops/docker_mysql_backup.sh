#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE_RELATIVE_PATH="${ENV_FILE_RELATIVE_PATH:-src/backend/.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-docker/docker-compose.yml}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose/prod.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai-for-investor}"

compose_args=(--project-directory "$PROJECT_ROOT" --project-name "$COMPOSE_PROJECT_NAME")
if [[ -n "$ENV_FILE_RELATIVE_PATH" ]]; then
    compose_args+=(--env-file "$ENV_FILE_RELATIVE_PATH")
fi
if [[ -n "$COMPOSE_BASE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_BASE_FILE")
fi
if [[ -n "$COMPOSE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_FILE")
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="${1:-runtime/backups/mysql_${timestamp}.sql.gz}"
if [[ "$backup_path" != /* ]]; then
    backup_path="$PROJECT_ROOT/$backup_path"
fi
if [[ -e "$backup_path" || -e "$backup_path.sha256" ]]; then
    echo "Refusing to overwrite existing backup: $backup_path" >&2
    exit 2
fi
backup_dir="$(dirname "$backup_path")"
if [[ ! -d "$backup_dir" ]]; then
    mkdir -p -m 700 "$backup_dir"
fi
umask 077
temporary_path="${backup_path}.tmp.$$"
trap 'rm -f "$temporary_path"' EXIT

docker compose "${compose_args[@]}" exec -T mysql sh -ec \
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysqldump --user=root --single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF --databases "$MYSQL_DATABASE"' \
    | gzip -c > "$temporary_path"
gzip -t "$temporary_path"
mv "$temporary_path" "$backup_path"
chmod 600 "$backup_path"
(
    cd "$(dirname "$backup_path")"
    sha256sum "$(basename "$backup_path")" > "$(basename "$backup_path").sha256"
)
chmod 600 "${backup_path}.sha256"
trap - EXIT

printf 'MySQL backup created: %s\n' "$backup_path"
