#!/bin/sh
set -u

log() {
    printf '[certbot-renew] %s\n' "$*"
}

trap 'exit 0' TERM INT
log "Automatic renewal loop started for certificate ${CERT_NAME:-configured}"
while :; do
    if certbot renew --webroot -w /var/www/certbot; then
        log "Renewal check completed"
    else
        status=$?
        log "Renewal command failed with exit status $status; existing Nginx TLS remains loaded"
    fi
    sleep 12h &
    wait "$!" || true
done
