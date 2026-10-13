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

read_env_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

SERVER_DOMAIN="${SERVER_DOMAIN:-$(read_env_value SERVER_DOMAIN)}"
CERT_NAME="${CERT_NAME:-$(read_env_value CERT_NAME)}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-$(read_env_value CERTBOT_EMAIL)}"
ACME_DIRECTORY_URL="${ACME_DIRECTORY_URL:-$(read_env_value ACME_DIRECTORY_URL)}"
SERVER_DOMAIN="${SERVER_DOMAIN:-}"
CERT_NAME="${CERT_NAME:-$SERVER_DOMAIN}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-admin@$SERVER_DOMAIN}"

if [[ ! "$SERVER_DOMAIN" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]; then
    echo "SERVER_DOMAIN must be a fully qualified DNS name; IP/localhost mode is HTTP-only." >&2
    exit 2
fi
if [[ "$CERT_NAME" == "." || "$CERT_NAME" == ".." \
    || ! "$CERT_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "CERT_NAME may contain only letters, digits, dots, underscores, and hyphens." >&2
    exit 2
fi
if [[ ! "$CERTBOT_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
    echo "CERTBOT_EMAIL must be a valid email address." >&2
    exit 2
fi

compose_args=(--project-directory "$PROJECT_ROOT" --project-name "$COMPOSE_PROJECT_NAME")
if [[ "$ENV_FILE_RELATIVE_PATH" != "" ]]; then
    compose_args+=(--env-file "$ENV_FILE")
fi
if [[ -n "$COMPOSE_BASE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_BASE_FILE")
fi
if [[ -n "$COMPOSE_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_FILE")
fi
if [[ -n "$COMPOSE_EXTRA_FILE" ]]; then
    compose_args+=(-f "$COMPOSE_EXTRA_FILE")
fi

CONF_DIR="${CERTBOT_CONF_DIR:-$PROJECT_ROOT/runtime/certbot/conf}"
WWW_DIR="${CERTBOT_WWW_DIR:-$PROJECT_ROOT/runtime/certbot/www}"
CERT_DIR="$CONF_DIR/live/$CERT_NAME"
mkdir -p "$CONF_DIR" "$WWW_DIR/.well-known/acme-challenge"
chmod 700 "$CONF_DIR" "$WWW_DIR"
previous_tls_enabled="$(read_env_value TLS_ENABLED)"
previous_tls_enabled="${previous_tls_enabled:-false}"
backup_dir="$(mktemp -d "$CONF_DIR/.certbot-init-${CERT_NAME}.XXXXXX")"
chmod 700 "$backup_dir"
rollback_on_exit=true
state_restore_attempted=false
state_restore_succeeded=false
frontend_activation_attempted=false
frontend_rollback_attempted=false
frontend_rollback_succeeded=false

backup_certificate_lineage() {
    local relative_path
    for relative_path in "live/$CERT_NAME" "archive/$CERT_NAME" "renewal/$CERT_NAME.conf"; do
        if [[ -e "$CONF_DIR/$relative_path" || -L "$CONF_DIR/$relative_path" ]]; then
            mkdir -p "$backup_dir/$(dirname "$relative_path")"
            cp -a "$CONF_DIR/$relative_path" "$backup_dir/$relative_path"
        fi
    done
}

restore_certificate_lineage() {
    local relative_path
    for relative_path in "live/$CERT_NAME" "archive/$CERT_NAME" "renewal/$CERT_NAME.conf"; do
        rm -rf "$CONF_DIR/$relative_path"
        if [[ -e "$backup_dir/$relative_path" || -L "$backup_dir/$relative_path" ]]; then
            mkdir -p "$CONF_DIR/$(dirname "$relative_path")"
            cp -a "$backup_dir/$relative_path" "$CONF_DIR/$relative_path"
        fi
    done
}

cleanup_certificate_backup() {
    if [[ -n "$backup_dir" ]]; then
        if [[ "$rollback_on_exit" == "true" \
            || ( "$frontend_activation_attempted" == "true" \
                && "$frontend_rollback_attempted" == "false" ) ]]; then
            if ! restore_previous_state; then
                echo "Failed to restore the previous certificate lineage or TLS mode during cleanup." >&2
            fi
            if [[ "$frontend_activation_attempted" == "true" \
                && "$frontend_rollback_attempted" == "false" ]]; then
                if ! restore_previous_frontend; then
                    echo "Failed to restore the previous frontend during cleanup." >&2
                fi
            fi
        fi
        rm -rf "$backup_dir"
    fi
}

certificate_matches_domain() {
    [[ -r "$CERT_DIR/fullchain.pem" && -r "$CERT_DIR/privkey.pem" ]] || return 1
    openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -checkhost "$SERVER_DOMAIN" >/dev/null 2>&1 || return 1
    openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -checkend 0 >/dev/null 2>&1 || return 1

    local temp_dir
    temp_dir="$(mktemp -d)"
    if ! openssl x509 -in "$CERT_DIR/fullchain.pem" -pubkey -noout > "$temp_dir/cert.pub" \
        || ! openssl pkey -pubin -in "$temp_dir/cert.pub" -outform DER -out "$temp_dir/cert.der" \
        || ! openssl pkey -in "$CERT_DIR/privkey.pem" -pubout -outform DER -out "$temp_dir/key.der" \
        || ! cmp -s "$temp_dir/cert.der" "$temp_dir/key.der"; then
        rm -rf "$temp_dir"
        return 1
    fi
    rm -rf "$temp_dir"
}

set_tls_enabled() {
    local value="$1"
    local temp_file
    temp_file="$(mktemp "$(dirname "$ENV_FILE")/.env.tls.XXXXXX")"
    awk -F= -v value="$value" '
        BEGIN { replaced = 0 }
        $1 == "TLS_ENABLED" { print "TLS_ENABLED=" value; replaced = 1; next }
        { print }
        END { if (!replaced) print "TLS_ENABLED=" value }
    ' "$ENV_FILE" > "$temp_file"
    chmod 600 "$temp_file"
    mv "$temp_file" "$ENV_FILE"
}

restore_previous_state() {
    if [[ "$state_restore_attempted" == "true" ]]; then
        [[ "$state_restore_succeeded" == "true" ]] && return 0
        return 1
    fi
    state_restore_attempted=true
    if ! restore_certificate_lineage; then
        echo "Failed to restore the previous certificate lineage." >&2
        return 1
    fi
    if ! set_tls_enabled "$previous_tls_enabled"; then
        echo "Failed to restore TLS_ENABLED=$previous_tls_enabled." >&2
        return 1
    fi
    state_restore_succeeded=true
    rollback_on_exit=false
}

restore_previous_frontend() {
    if [[ "$frontend_rollback_attempted" == "true" ]]; then
        [[ "$frontend_rollback_succeeded" == "true" ]] && return 0
        return 1
    fi
    frontend_rollback_attempted=true
    if ! restore_previous_state; then
        return 1
    fi
    if ! docker compose "${compose_args[@]}" up -d --no-deps --force-recreate frontend; then
        echo "Failed to restart the frontend after restoring the previous certificate and TLS mode." >&2
        return 1
    fi
    if ! wait_for_nginx_master; then
        echo "The restored frontend did not reach a running Nginx master." >&2
        return 1
    fi
    frontend_rollback_succeeded=true
}

wait_for_nginx_master() {
    local attempt
    for attempt in $(seq 1 30); do
        if docker compose "${compose_args[@]}" exec -T frontend sh -c '
            [ -r /run/nginx.pid ] || exit 1
            pid="$(cat /run/nginx.pid)"
            case "$pid" in ""|*[!0-9]*) exit 1 ;; esac
            kill -0 "$pid" 2>/dev/null
        '; then
            return 0
        fi
        sleep 1
    done
    echo "Nginx master did not become ready before TLS reload." >&2
    return 1
}

reload_nginx_after_startup() {
    local attempt
    local output
    for attempt in $(seq 1 10); do
        if ! wait_for_nginx_master; then
            return 1
        fi
        if output="$(docker compose "${compose_args[@]}" exec -T frontend nginx -s reload 2>&1)"; then
            printf '%s\n' "$output"
            return 0
        fi
        if [[ "$output" == *'invalid PID number "" in "/run/nginx.pid"'* ]]; then
            echo "Nginx PID file is still being initialized; retrying reload ($attempt/10)." >&2
            sleep 1
            continue
        fi
        printf '%s\n' "$output" >&2
        return 1
    done
    echo "Nginx reload did not succeed after the PID file initialization retries." >&2
    return 1
}

trap cleanup_certificate_backup EXIT

backup_certificate_lineage
echo "Starting HTTP bootstrap for $SERVER_DOMAIN; certificate material is backed up before issuance."
docker compose "${compose_args[@]}" up -d frontend

certbot_args=(certonly --webroot --webroot-path /var/www/certbot --domain "$SERVER_DOMAIN" \
    --cert-name "$CERT_NAME" --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email --non-interactive)
if [[ -n "$ACME_DIRECTORY_URL" ]]; then
    certbot_args+=(--server "$ACME_DIRECTORY_URL")
fi

echo "Requesting certificate for $SERVER_DOMAIN from ${ACME_DIRECTORY_URL:-the configured ACME default}."
if ! docker compose "${compose_args[@]}" run --rm --no-deps --entrypoint certbot certbot "${certbot_args[@]}"; then
    echo "Certificate issuance failed; restoring the previous certificate and TLS mode." >&2
    exit 1
fi

if ! certificate_matches_domain; then
    echo "Issued certificate does not match $SERVER_DOMAIN, is expired, or has a mismatched private key." >&2
    exit 1
fi

frontend_activation_attempted=true
set_tls_enabled true
if docker compose "${compose_args[@]}" up -d --no-deps --force-recreate frontend \
    && docker compose "${compose_args[@]}" exec -T frontend nginx -t \
    && reload_nginx_after_startup; then
    if rendered_config="$(docker compose "${compose_args[@]}" exec -T frontend nginx -T 2>&1)"; then
        :
    else
        rendered_config_status=$?
        printf '%s\n' "$rendered_config" >&2
        exit "$rendered_config_status"
    fi
    has_tls_listener=false
    has_expected_certificate_path=false
    [[ "$rendered_config" == *"listen 443 ssl;"* ]] && has_tls_listener=true
    [[ "$rendered_config" == *"/etc/letsencrypt/live/$CERT_NAME/fullchain.pem"* ]] \
        && has_expected_certificate_path=true
    if [[ "$has_tls_listener" != true || "$has_expected_certificate_path" != true ]]; then
        printf '%s\n' "$rendered_config" \
            | grep -E 'listen 443 ssl;|ssl_certificate |nginx: \[|service .* is not running' >&2 || true
        docker compose "${compose_args[@]}" logs --no-color frontend >&2 || true
        if ! restore_previous_frontend; then
            echo "TLS rollback could not restore the previous frontend." >&2
        fi
        echo "Nginx did not load the configured TLS server (listener=$has_tls_listener, certificate_path=$has_expected_certificate_path); restored TLS_ENABLED=$previous_tls_enabled." >&2
        exit 1
    fi
    rollback_on_exit=false
    frontend_activation_attempted=false
    echo "TLS is enabled for $SERVER_DOMAIN using certificate $CERT_NAME."
else
    if ! restore_previous_frontend; then
        echo "TLS rollback could not restore the previous frontend." >&2
    fi
    echo "TLS activation failed; restoring the previous certificate and TLS_ENABLED=$previous_tls_enabled." >&2
    exit 1
fi
