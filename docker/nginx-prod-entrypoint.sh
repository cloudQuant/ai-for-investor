#!/bin/sh
set -eu

SERVER_DOMAIN="${SERVER_DOMAIN:-localhost}"
CERT_NAME="${CERT_NAME:-$SERVER_DOMAIN}"
TLS_ENABLED="${TLS_ENABLED:-false}"
HTTP_TEMPLATE="/etc/nginx/templates/http.conf.template"
TLS_TEMPLATE="/etc/nginx/templates/tls.conf.template"
ACTIVE_CONFIG="/etc/nginx/conf.d/default.conf"
CERT_DIR="/etc/letsencrypt/live/$CERT_NAME"

log() {
    printf '[nginx-bootstrap] %s\n' "$*"
}

case "$SERVER_DOMAIN" in
    ""|*[!A-Za-z0-9.:-]*)
        log "Invalid SERVER_DOMAIN; refusing to render an Nginx configuration"
        exit 2
        ;;
esac
case "$CERT_NAME" in
    ""|.|..|*[!A-Za-z0-9._-]*)
        log "Invalid CERT_NAME; refusing to render an Nginx configuration"
        exit 2
        ;;
esac
case "$TLS_ENABLED" in
    true|false) ;;
    *)
        log "TLS_ENABLED must be true or false"
        exit 2
        ;;
esac

case "$SERVER_DOMAIN" in
    localhost|*:* )
        log "IP-only or localhost mode is HTTP-only; TLS is disabled for $SERVER_DOMAIN"
        TLS_ENABLED=false
        ;;
    *[!0-9.]* ) ;;
    *)
        # A numeric-only host is an IP literal, not a DNS name.
        log "IP-only mode is HTTP-only; TLS is disabled for $SERVER_DOMAIN"
        TLS_ENABLED=false
        ;;
esac

valid_certificate() {
    cert="$CERT_DIR/fullchain.pem"
    key="$CERT_DIR/privkey.pem"
    [ -r "$cert" ] && [ -r "$key" ] || return 1
    openssl x509 -in "$cert" -noout -checkend 0 >/dev/null 2>&1 || return 1
    openssl x509 -in "$cert" -noout -checkhost "$SERVER_DOMAIN" >/dev/null 2>&1 || return 1

    tmp_dir="$(mktemp -d)"
    if ! openssl x509 -in "$cert" -pubkey -noout > "$tmp_dir/cert.pub" \
        || ! openssl pkey -pubin -in "$tmp_dir/cert.pub" -outform DER -out "$tmp_dir/cert.der" \
        || ! openssl pkey -in "$key" -pubout -outform DER -out "$tmp_dir/key.der" \
        || ! cmp -s "$tmp_dir/cert.der" "$tmp_dir/key.der"; then
        rm -rf "$tmp_dir"
        return 1
    fi
    rm -rf "$tmp_dir"
    return 0
}

render_http() {
    envsubst '${SERVER_DOMAIN}' < "$HTTP_TEMPLATE" > "$ACTIVE_CONFIG"
}

render_tls() {
    envsubst '${SERVER_DOMAIN} ${CERT_NAME}' < "$TLS_TEMPLATE" > "$ACTIVE_CONFIG"
}

cert_fingerprint() {
    [ -r "$CERT_DIR/fullchain.pem" ] && [ -r "$CERT_DIR/privkey.pem" ] || return 1
    cert_hash="$(sha256sum "$CERT_DIR/fullchain.pem" | cut -d ' ' -f 1)"
    key_hash="$(sha256sum "$CERT_DIR/privkey.pem" | cut -d ' ' -f 1)"
    printf '%s:%s' "$cert_hash" "$key_hash"
}

if [ "$TLS_ENABLED" = "true" ]; then
    if valid_certificate; then
        render_tls
        if nginx -t; then
            log "TLS enabled for $SERVER_DOMAIN using certificate $CERT_NAME"
        else
            log "TLS config validation failed; starting with HTTP bootstrap config"
            render_http
        fi
    else
        log "No valid matching certificate for $SERVER_DOMAIN; serving HTTP bootstrap"
        render_http
    fi
else
    log "TLS is disabled; serving HTTP only for $SERVER_DOMAIN (IP-only mode is supported)"
    render_http
fi

nginx -t
if [ "$#" -gt 0 ] && [ "$1" = "nginx" ]; then
    shift
fi
if [ "$#" -eq 0 ]; then
    set -- -g 'daemon off;'
fi
nginx "$@" &
nginx_pid=$!
active_fingerprint=""
if [ "$TLS_ENABLED" = "true" ] && valid_certificate; then
    active_fingerprint="$(cert_fingerprint || true)"
fi

cleanup() {
    kill -TERM "$nginx_pid" 2>/dev/null || true
    wait "$nginx_pid" 2>/dev/null || true
}
trap cleanup TERM INT

while kill -0 "$nginx_pid" 2>/dev/null; do
    sleep 15 &
    wait "$!" || true
    [ "$TLS_ENABLED" = "true" ] || continue
    valid_certificate || continue
    new_fingerprint="$(cert_fingerprint || true)"
    [ -n "$new_fingerprint" ] && [ "$new_fingerprint" != "$active_fingerprint" ] || continue

    previous_config="$(mktemp)"
    cp "$ACTIVE_CONFIG" "$previous_config"
    render_tls
    if nginx -t && nginx -s reload; then
        active_fingerprint="$new_fingerprint"
        log "Validated renewed certificate for $SERVER_DOMAIN; Nginx reload requested"
    else
        cp "$previous_config" "$ACTIVE_CONFIG"
        log "Renewed certificate failed validation; keeping the previously loaded config"
    fi
    rm -f "$previous_config"
done

wait "$nginx_pid"
