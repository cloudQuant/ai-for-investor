#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$(mktemp -d /tmp/iter202-d14-evidence.XXXXXX)}"
RUN_ID="iter202-d14-$(date +%Y%m%d%H%M%S)-$$"
RUN_DIR="$EVIDENCE_ROOT/$RUN_ID"
PROJECT_NAME="$RUN_ID"
DOMAIN="investor.iter202.test"
CERT_NAME="iter202-d14-test"
DEFAULT_NGINX_IMAGE="iter202-d14-nginx-runtime:20261012"
NGINX_IMAGE="${NGINX_IMAGE:-$DEFAULT_NGINX_IMAGE}"
CERTBOT_IMAGE="certbot/certbot:latest"
PEBBLE_IMAGE="ghcr.io/letsencrypt/pebble:latest"
CHALLTESTSRV_IMAGE="ghcr.io/letsencrypt/pebble-challtestsrv:latest"
COMPOSE_FILE="$RUN_DIR/compose.yml"
ENV_FILE="$RUN_DIR/test.env"
CONF_DIR="$RUN_DIR/certbot/conf"
WWW_DIR="$RUN_DIR/certbot/www"
PEBBLE_API_CA="$RUN_DIR/pebble-api-ca.crt"
PEBBLE_API_SERVER_CERT="$RUN_DIR/pebble-api-server.crt"
PEBBLE_API_SERVER_KEY="$RUN_DIR/pebble-api-server.key"
RUN_LOG="$RUN_DIR/run.log"
PORT_LIST=""
HTTP_HOST_PORT=""
HTTPS_HOST_PORT=""
PEBBLE_MGMT_PORT=""
CHALLTESTSRV_PORT=""
SAN_NEGATIVE_CONTAINER=""

mkdir -p "$RUN_DIR" "$CONF_DIR" "$WWW_DIR"
chmod 700 "$RUN_DIR" "$RUN_DIR/certbot" "$CONF_DIR" "$WWW_DIR"
exec > >(tee -a "$RUN_LOG") 2>&1
set -x

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

compose() {
    docker compose --project-directory "$PROJECT_ROOT" --project-name "$PROJECT_NAME" \
        --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    set +e
    if [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]]; then
        compose logs --no-color --timestamps \
            | sed -E 's#(/\.well-known/acme-challenge/)[^[:space:]]+#\1[redacted]#g' \
            > "$RUN_DIR/compose.log" 2>&1
        compose down --remove-orphans
        rm -f "$ENV_FILE"
    fi
    if [[ -n "$SAN_NEGATIVE_CONTAINER" ]]; then
        docker rm -f "$SAN_NEGATIVE_CONTAINER" >/dev/null 2>&1 || true
    fi
    if [[ -d "$CONF_DIR" ]]; then
        find "$CONF_DIR" -type f \( -name 'privkey*.pem' -o -name 'private_key.json' \) -delete
    fi
    rm -f "$RUN_DIR/pebble-api-ca.key" "$PEBBLE_API_SERVER_KEY"
    printf '%s\n' "$status" > "$RUN_DIR/exit-status.txt"
    if [[ "$status" -eq 0 ]]; then
        printf 'PASS\n' > "$RUN_DIR/outcome.txt"
    else
        printf 'FAIL\n' > "$RUN_DIR/outcome.txt"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

command -v docker >/dev/null || fail "docker is required"
command -v curl >/dev/null || fail "curl is required"
command -v openssl >/dev/null || fail "openssl is required"
command -v shasum >/dev/null || fail "shasum is required"
PORT_LIST="$(/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -c 'import socket; sockets = [socket.socket() for _ in range(4)]; [sock.bind(("127.0.0.1", 0)) for sock in sockets]; print(" ".join(str(sock.getsockname()[1]) for sock in sockets))')"
read -r HTTP_HOST_PORT HTTPS_HOST_PORT PEBBLE_MGMT_PORT CHALLTESTSRV_PORT <<< "$PORT_LIST"
printf 'loopback ports: http=%s https=%s pebble-management=%s challtestsrv-management=%s\n' \
    "$HTTP_HOST_PORT" "$HTTPS_HOST_PORT" "$PEBBLE_MGMT_PORT" "$CHALLTESTSRV_PORT" \
    | tee "$RUN_DIR/loopback-ports.txt"
docker compose version
docker version
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' > "$RUN_DIR/containers-before.txt"

if ! docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1; then
    if [[ "$NGINX_IMAGE" == "$DEFAULT_NGINX_IMAGE" ]]; then
        docker build --file "$PROJECT_ROOT/src/frontend/Dockerfile" \
            --target nginx-runtime --tag "$NGINX_IMAGE" "$PROJECT_ROOT/src/frontend"
    else
        docker pull "$NGINX_IMAGE"
    fi
fi
docker pull "$CERTBOT_IMAGE"
docker pull "$PEBBLE_IMAGE"
docker pull "$CHALLTESTSRV_IMAGE"
for image in "$NGINX_IMAGE" "$CERTBOT_IMAGE" "$PEBBLE_IMAGE" "$CHALLTESTSRV_IMAGE"; do
    docker image inspect --format '{{.Id}} {{json .RepoDigests}}' "$image"
done | tee "$RUN_DIR/image-digests.txt"

for source in \
    docker/nginx.prod.conf \
    docker/nginx.prod.http.conf.template \
    docker/nginx.prod.tls.conf.template \
    docker/nginx.prod.locations.conf \
    docker/nginx-prod-entrypoint.sh \
    docker/entrypoint-certbot-renew.sh \
    scripts/ops/certbot-init.sh \
    scripts/ops/certbot-renew.sh \
    src/frontend/Dockerfile \
    scripts/ops/test_tls_bootstrap_pebble.sh; do
    shasum -a 256 "$PROJECT_ROOT/$source"
done | tee "$RUN_DIR/source-hashes.sha256"

openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -keyout "$RUN_DIR/pebble-api-ca.key" -out "$PEBBLE_API_CA" \
    -subj "/CN=iter202-d14-pebble-api-ca" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl req -newkey rsa:2048 -nodes \
    -keyout "$PEBBLE_API_SERVER_KEY" -out "$RUN_DIR/pebble-api-server.csr" \
    -subj "/CN=pebble"
cat > "$RUN_DIR/pebble-api-server.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:pebble
EOF
openssl x509 -req -in "$RUN_DIR/pebble-api-server.csr" \
    -CA "$PEBBLE_API_CA" -CAkey "$RUN_DIR/pebble-api-ca.key" \
    -CAcreateserial -out "$PEBBLE_API_SERVER_CERT" -days 2 -sha256 \
    -extfile "$RUN_DIR/pebble-api-server.ext"
chmod 600 "$RUN_DIR/pebble-api-ca.key" "$PEBBLE_API_SERVER_KEY"

cat > "$RUN_DIR/pebble-config.json" <<EOF
{
  "pebble": {
    "listenAddress": "0.0.0.0:14000",
    "managementListenAddress": "0.0.0.0:15000",
    "certificate": "/test/pebble-api-server.crt",
    "privateKey": "/test/pebble-api-server.key",
    "httpPort": 80,
    "tlsPort": 5001,
    "ocspResponderURL": "",
    "externalAccountBindingRequired": false,
    "domainBlocklist": ["blocked-domain.example"],
    "retryAfter": {"authz": 1, "order": 1},
    "keyAlgorithm": "ecdsa",
    "profiles": {
      "default": {
        "description": "Seven-day local integration certificate",
        "validityPeriod": 604800
      }
    }
  }
}
EOF

cat > "$ENV_FILE" <<EOF
SERVER_DOMAIN=$DOMAIN
CERT_NAME=$CERT_NAME
CERTBOT_EMAIL=admin@example.test
ACME_DIRECTORY_URL=https://pebble:14000/dir
TLS_ENABLED=false
CERTBOT_CONF_DIR=$CONF_DIR
CERTBOT_WWW_DIR=$WWW_DIR
NGINX_IMAGE=$NGINX_IMAGE
CERTBOT_IMAGE=$CERTBOT_IMAGE
PEBBLE_IMAGE=$PEBBLE_IMAGE
CHALLTESTSRV_IMAGE=$CHALLTESTSRV_IMAGE
PEBBLE_API_CA=$PEBBLE_API_CA
EOF
chmod 600 "$ENV_FILE"

cat > "$RUN_DIR/backend.conf" <<'EOF'
server {
    listen 8000;
    location / {
        return 200 "iter202 backend stub\n";
    }
}
EOF
cat > "$RUN_DIR/nginx.conf" <<'EOF'
worker_processes 1;
events {
    worker_connections 256;
}
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    include /etc/nginx/conf.d/*.conf;
}
EOF

cat > "$COMPOSE_FILE" <<EOF
services:
  backend:
    image: $NGINX_IMAGE
    restart: "no"
    volumes:
      - "$RUN_DIR/nginx.conf:/etc/nginx/nginx.conf:ro"
      - "$RUN_DIR/backend.conf:/etc/nginx/conf.d/default.conf:ro"
  frontend:
    image: $NGINX_IMAGE
    restart: "no"
    ports:
      - "127.0.0.1:$HTTP_HOST_PORT:80"
      - "127.0.0.1:$HTTPS_HOST_PORT:443"
    volumes:
      - "$RUN_DIR/nginx.conf:/etc/nginx/nginx.conf:ro"
      - "$PROJECT_ROOT/docker/nginx.prod.http.conf.template:/etc/nginx/templates/http.conf.template:ro"
      - "$PROJECT_ROOT/docker/nginx.prod.tls.conf.template:/etc/nginx/templates/tls.conf.template:ro"
      - "$PROJECT_ROOT/docker/nginx.prod.locations.conf:/etc/nginx/conf.d/ai-investor-proxy.inc:ro"
      - "$PROJECT_ROOT/docker/nginx-prod-entrypoint.sh:/usr/local/bin/nginx-prod-entrypoint.sh:ro"
      - "$CONF_DIR:/etc/letsencrypt:ro"
      - "$WWW_DIR:/var/www/certbot:ro"
    entrypoint: ["/bin/sh", "/usr/local/bin/nginx-prod-entrypoint.sh"]
    command: ["nginx", "-g", "daemon off;"]
    environment:
      SERVER_DOMAIN: \${SERVER_DOMAIN}
      CERT_NAME: \${CERT_NAME}
      TLS_ENABLED: \${TLS_ENABLED}
  certbot:
    image: $CERTBOT_IMAGE
    volumes:
      - "$CONF_DIR:/etc/letsencrypt"
      - "$WWW_DIR:/var/www/certbot"
      - "$PEBBLE_API_CA:/test/pebble-api-ca.crt:ro"
    environment:
      REQUESTS_CA_BUNDLE: /test/pebble-api-ca.crt
  pebble:
    image: $PEBBLE_IMAGE
    command: ["-config", "/test/pebble-config.json", "-strict", "-dnsserver", "challtestsrv:8053"]
    environment:
      PEBBLE_VA_NOSLEEP: "1"
      PEBBLE_WFE_NONCEREJECT: "0"
    ports:
      - "127.0.0.1:$PEBBLE_MGMT_PORT:15000"
    volumes:
      - "$RUN_DIR/pebble-config.json:/test/pebble-config.json:ro"
      - "$PEBBLE_API_SERVER_CERT:/test/pebble-api-server.crt:ro"
      - "$PEBBLE_API_SERVER_KEY:/test/pebble-api-server.key:ro"
  challtestsrv:
    image: $CHALLTESTSRV_IMAGE
    command: ["-defaultIPv6", "", "-defaultIPv4", "127.0.0.1"]
    ports:
      - "127.0.0.1:$CHALLTESTSRV_PORT:8055"
EOF

COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
COMPOSE_BASE_FILE="" \
COMPOSE_FILE="$COMPOSE_FILE" \
COMPOSE_EXTRA_FILE="" \
compose config > "$RUN_DIR/compose-resolved.yml"

if find "$CONF_DIR" -mindepth 1 -print -quit | grep -q .; then
    fail "certificate configuration directory was not empty before bootstrap"
fi
printf 'empty certificate directory confirmed: %s\n' "$CONF_DIR" | tee "$RUN_DIR/blank-cert-dir.txt"

compose up -d pebble challtestsrv
for attempt in $(seq 1 60); do
    if curl --silent --show-error --insecure --fail \
        "https://127.0.0.1:$PEBBLE_MGMT_PORT/roots/0" \
        -o "$RUN_DIR/pebble-root.pem"; then
        break
    fi
    [[ "$attempt" -lt 60 ]] || fail "Pebble management API did not become ready"
    sleep 1
done
compose up -d backend
# Start Nginx in HTTP bootstrap mode so Pebble's local DNS can resolve the
# custom test domain to its live container address before Certbot validates it.
compose up -d frontend
NGINX_HOST_IP="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(compose ps -q frontend)")"
[[ -n "$NGINX_HOST_IP" ]] || fail "HTTP bootstrap Nginx has no isolated network address"

curl --silent --show-error --fail -X POST -H 'Content-Type: application/json' \
    -d "{\"ip\":\"$NGINX_HOST_IP\"}" \
    "http://127.0.0.1:$CHALLTESTSRV_PORT/set-default-ipv4"

COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
COMPOSE_BASE_FILE="" \
COMPOSE_FILE="$COMPOSE_FILE" \
COMPOSE_EXTRA_FILE="" \
CERTBOT_CONF_DIR="$CONF_DIR" \
CERTBOT_WWW_DIR="$WWW_DIR" \
./scripts/ops/certbot-init.sh 2>&1 | tee "$RUN_DIR/bootstrap.log"
grep -Fq 'configuration file /etc/nginx/nginx.conf test is successful' "$RUN_DIR/bootstrap.log" \
    || fail "initial certificate activation did not run nginx -t"
grep -Fq 'signal process started' "$RUN_DIR/bootstrap.log" \
    || fail "initial certificate activation did not request an Nginx reload"

HTTP_PORT="$HTTP_HOST_PORT"
HTTPS_PORT="$HTTPS_HOST_PORT"
wait_for_https_restore() {
    local evidence_path="$1"
    local errors_path="$2"
    local attempt
    for attempt in $(seq 1 20); do
        if curl --silent --insecure --fail --max-time 2 \
            --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
            "https://$DOMAIN:$HTTPS_PORT/healthz" \
            -o "$evidence_path" 2> "$errors_path"; then
            printf 'ready_on_attempt=%s\n' "$attempt" > "${evidence_path%.txt}.ready.txt"
            return 0
        fi
        sleep 1
    done
    cat "$errors_path" >&2
    return 1
}
curl --silent --show-error --fail --resolve "$DOMAIN:$HTTP_PORT:127.0.0.1" \
    "http://$DOMAIN:$HTTP_PORT/healthz" | tee "$RUN_DIR/http-healthz.txt"
curl --silent --show-error --insecure --fail --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
    "https://$DOMAIN:$HTTPS_PORT/healthz" | tee "$RUN_DIR/https-healthz.txt"

PRESENTED_CERT="$RUN_DIR/tls-presented.pem"
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2> "$RUN_DIR/openssl-s_client.log" \
    | openssl x509 -out "$PRESENTED_CERT"
openssl x509 -in "$PRESENTED_CERT" -noout -checkhost "$DOMAIN"
openssl x509 -in "$PRESENTED_CERT" -noout -checkend 0
openssl x509 -in "$PRESENTED_CERT" -noout -subject -issuer -serial -dates -ext subjectAltName \
    | tee "$RUN_DIR/tls-certificate.txt"
CERT_PATH="$CONF_DIR/live/$CERT_NAME/fullchain.pem"
KEY_PATH="$CONF_DIR/live/$CERT_NAME/privkey.pem"
write_certificate_identity() {
    local destination="$1"
    {
        printf 'certificate_der_sha256='
        openssl x509 -in "$CERT_PATH" -outform DER | shasum -a 256 | awk '{print $1}'
        printf 'private_key_public_der_sha256='
        openssl pkey -in "$KEY_PATH" -pubout -outform DER \
            | shasum -a 256 | awk '{print $1}'
    } > "$destination"
}
openssl x509 -in "$CERT_PATH" -noout -checkhost "$DOMAIN"
openssl x509 -in "$CERT_PATH" -noout -checkend 0
openssl x509 -in "$CERT_PATH" -noout -subject -issuer -serial -dates -ext subjectAltName \
    > "$RUN_DIR/issued-certificate.txt"
openssl x509 -in "$PRESENTED_CERT" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.before-failures.txt"
openssl x509 -in "$CERT_PATH" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-lineage-fingerprint.before-failures.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-lineage-fingerprint.before-failures.txt"
openssl x509 -in "$CERT_PATH" -outform DER -out "$RUN_DIR/issued-leaf.der"
openssl x509 -in "$PRESENTED_CERT" -outform DER -out "$RUN_DIR/presented-leaf.der"
cmp "$RUN_DIR/issued-leaf.der" "$RUN_DIR/presented-leaf.der"
WRONG_DOMAIN="wrong.$DOMAIN"
set +e
docker run --rm --network none --volume "$CONF_DIR:/etc/letsencrypt:ro" \
    --entrypoint openssl "$NGINX_IMAGE" \
    x509 -in "/etc/letsencrypt/live/$CERT_NAME/fullchain.pem" -noout \
    -checkhost "$WRONG_DOMAIN" > "$RUN_DIR/san-negative-checkhost.txt" 2>&1
SAN_CHECKHOST_STATUS=$?
set -e
printf 'exit_status=%s\n' "$SAN_CHECKHOST_STATUS" >> "$RUN_DIR/san-negative-checkhost.txt"
[[ "$SAN_CHECKHOST_STATUS" -ne 0 ]] \
    || fail "OpenSSL accepted a domain outside the issued certificate SAN"
grep -Fq "does NOT match certificate" "$RUN_DIR/san-negative-checkhost.txt" \
    || fail "OpenSSL checkhost rejection output was not observable"
SAN_NEGATIVE_CONTAINER="$PROJECT_NAME-san-negative"
docker run --detach --name "$SAN_NEGATIVE_CONTAINER" --network none \
    --env "SERVER_DOMAIN=$WRONG_DOMAIN" --env "CERT_NAME=$CERT_NAME" --env TLS_ENABLED=true \
    --volume "$RUN_DIR/nginx.conf:/etc/nginx/nginx.conf:ro" \
    --volume "$CONF_DIR:/etc/letsencrypt:ro" \
    --volume "$PROJECT_ROOT/docker/nginx.prod.http.conf.template:/etc/nginx/templates/http.conf.template:ro" \
    --volume "$PROJECT_ROOT/docker/nginx.prod.tls.conf.template:/etc/nginx/templates/tls.conf.template:ro" \
    --volume "$PROJECT_ROOT/docker/nginx.prod.locations.conf:/etc/nginx/conf.d/ai-investor-proxy.inc:ro" \
    --volume "$PROJECT_ROOT/docker/nginx-prod-entrypoint.sh:/usr/local/bin/nginx-prod-entrypoint.sh:ro" \
    --entrypoint /bin/sh "$NGINX_IMAGE" /usr/local/bin/nginx-prod-entrypoint.sh nginx -g 'daemon off;' \
    > "$RUN_DIR/san-negative-container-id.txt"
for attempt in $(seq 1 20); do
    docker logs "$SAN_NEGATIVE_CONTAINER" > "$RUN_DIR/san-negative-nginx.log" 2>&1 || true
    if grep -Fq "No valid matching certificate for $WRONG_DOMAIN" \
        "$RUN_DIR/san-negative-nginx.log"; then
        break
    fi
    [[ "$attempt" -lt 20 ]] || fail "Nginx SAN-negative container did not finish validation"
    sleep 1
done
docker exec "$SAN_NEGATIVE_CONTAINER" cat /etc/nginx/conf.d/default.conf \
    > "$RUN_DIR/san-negative-nginx-config.txt"
grep -Fq "No valid matching certificate for $WRONG_DOMAIN" "$RUN_DIR/san-negative-nginx.log" \
    || fail "Nginx entrypoint did not reject the wrong SERVER_DOMAIN"
if grep -Fq 'listen 443 ssl;' "$RUN_DIR/san-negative-nginx-config.txt"; then
    fail "wrong SERVER_DOMAIN rendered a TLS listener"
fi
grep -Fq 'listen 80;' "$RUN_DIR/san-negative-nginx-config.txt" \
    || fail "wrong SERVER_DOMAIN did not render the HTTP fallback"
docker rm -f "$SAN_NEGATIVE_CONTAINER" >/dev/null
SAN_NEGATIVE_CONTAINER=""
openssl x509 -in "$CERT_PATH" -noout -serial | sed 's/.*=//' | tr 'A-F' 'a-f' \
    > "$RUN_DIR/certificate-serial.txt"
CERT_SERIAL="$(cat "$RUN_DIR/certificate-serial.txt")"
curl --silent --show-error --insecure --fail \
    "https://127.0.0.1:$PEBBLE_MGMT_PORT/cert-status-by-serial/$CERT_SERIAL" \
    > "$RUN_DIR/pebble-certificate-status.json"
grep -Eq '"Status"[[:space:]]*:[[:space:]]*"Valid"' "$RUN_DIR/pebble-certificate-status.json" \
    || fail "Pebble did not report the issued certificate as Valid"
set +x
compose logs --no-color pebble \
    | grep -F "Attempting to validate w/ HTTP: http://$DOMAIN:80/.well-known/acme-challenge/" \
    | sed -E 's#(/\.well-known/acme-challenge/)[^[:space:]]+#\1[redacted]#g' \
    > "$RUN_DIR/http-acme-validation.txt"
set -x
grep -Fq "http://$DOMAIN:80/.well-known/acme-challenge/[redacted]" \
    "$RUN_DIR/http-acme-validation.txt" \
    || fail "Pebble did not record HTTP-01 validation for the custom test domain"
write_certificate_identity "$RUN_DIR/certificate-identity.before-failures.txt"

# Fail only the host-side TLS reload request. Compose startup, config checks,
# ACME and rollback recreation continue to use the real Docker CLI.
REAL_DOCKER="$(command -v docker)"
mkdir -p "$RUN_DIR/test-bin"
cat > "$RUN_DIR/test-bin/docker" <<EOF
#!/bin/sh
state=0
if [ "\${ITER202_FAIL_NGINX_RELOAD:-false}" = true ]; then
    for arg in "\$@"; do
        case "\$state:\$arg" in
            0:exec) state=1 ;;
            1:-T) state=2 ;;
            2:frontend) state=3 ;;
            3:nginx) state=4 ;;
            4:-s) state=5 ;;
            5:reload)
                echo "Injected nginx -s reload failure" >&2
                exit 71
                ;;
            *)
                if [ "\$arg" = exec ]; then state=1; else state=0; fi
                ;;
        esac
    done
fi
if [ "\${ITER202_FAIL_CERTBOT_RENEWAL:-false}" = true ]; then
    state=0
    for arg in "\$@"; do
        case "\$state:\$arg" in
            0:run) state=1 ;;
            1:--rm) state=2 ;;
            2:--no-deps) state=3 ;;
            3:--entrypoint) state=4 ;;
            4:certbot) state=5 ;;
            5:certbot) state=6 ;;
            6:renew)
                echo "Injected certbot renew launch failure" >&2
                exit 72
                ;;
            *)
                if [ "\$arg" = run ]; then state=1; else state=0; fi
                ;;
        esac
    done
fi
if [ "\${ITER202_FAIL_NGINX_RENDER:-false}" = true ]; then
    state=0
    for arg in "\$@"; do
        case "\$state:\$arg" in
            0:exec) state=1 ;;
            1:-T) state=2 ;;
            2:frontend) state=3 ;;
            3:nginx) state=4 ;;
            4:-T)
                echo "Injected nginx config inspection failure" >&2
                exit 73
                ;;
            *)
                if [ "\$arg" = exec ]; then state=1; else state=0; fi
                ;;
        esac
    done
fi
exec "$REAL_DOCKER" "\$@"
EOF
chmod 700 "$RUN_DIR/test-bin/docker"
if ITER202_FAIL_NGINX_RELOAD=true \
    PATH="$RUN_DIR/test-bin:$PATH" \
    COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
    ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
    COMPOSE_BASE_FILE="" \
    COMPOSE_FILE="$COMPOSE_FILE" \
    COMPOSE_EXTRA_FILE="" \
    CERTBOT_CONF_DIR="$CONF_DIR" \
    CERTBOT_WWW_DIR="$WWW_DIR" \
    ./scripts/ops/certbot-init.sh > "$RUN_DIR/activation-failure.log" 2>&1; then
    fail "TLS activation failure injection unexpectedly succeeded"
else
    ACTIVATION_FAILURE_STATUS=$?
fi
cat "$RUN_DIR/activation-failure.log"
[[ "$ACTIVATION_FAILURE_STATUS" -ne 0 ]] \
    || fail "TLS activation failure did not return nonzero"
grep -Fq 'Injected nginx -s reload failure' "$RUN_DIR/activation-failure.log" \
    || fail "TLS activation failure injection did not reach the reload path"
grep -Fq 'TLS activation failed; restoring the previous certificate and TLS_ENABLED=true.' \
    "$RUN_DIR/activation-failure.log" \
    || fail "TLS activation rollback was not observable"
write_certificate_identity "$RUN_DIR/certificate-identity.after-activation-failure.txt"
cmp "$RUN_DIR/certificate-identity.before-failures.txt" \
    "$RUN_DIR/certificate-identity.after-activation-failure.txt"
[[ "$(grep '^TLS_ENABLED=' "$ENV_FILE")" = 'TLS_ENABLED=true' ]] \
    || fail "failed TLS activation changed the previously enabled TLS mode"
wait_for_https_restore "$RUN_DIR/https-after-activation-failure.txt" \
    "$RUN_DIR/https-after-activation-failure-errors.txt" \
    || fail "the previous TLS frontend did not recover after activation rollback"
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2>/dev/null | openssl x509 -out "$RUN_DIR/tls-after-activation-failure.pem"
openssl x509 -in "$RUN_DIR/tls-after-activation-failure.pem" -outform DER \
    -out "$RUN_DIR/tls-after-activation-failure.der"
cmp "$RUN_DIR/presented-leaf.der" "$RUN_DIR/tls-after-activation-failure.der"
openssl x509 -in "$RUN_DIR/tls-after-activation-failure.pem" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.after-activation-failure.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-served-fingerprint.after-activation-failure.txt"

if ITER202_FAIL_NGINX_RENDER=true \
    PATH="$RUN_DIR/test-bin:$PATH" \
    COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
    ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
    COMPOSE_BASE_FILE="" \
    COMPOSE_FILE="$COMPOSE_FILE" \
    COMPOSE_EXTRA_FILE="" \
    CERTBOT_CONF_DIR="$CONF_DIR" \
    CERTBOT_WWW_DIR="$WWW_DIR" \
    ./scripts/ops/certbot-init.sh > "$RUN_DIR/activation-trap-failure.log" 2>&1; then
    fail "post-activation cleanup failure injection unexpectedly succeeded"
else
    ACTIVATION_TRAP_FAILURE_STATUS=$?
fi
cat "$RUN_DIR/activation-trap-failure.log"
[[ "$ACTIVATION_TRAP_FAILURE_STATUS" -ne 0 ]] \
    || fail "post-activation failure did not preserve its nonzero status"
grep -Fq 'Injected nginx config inspection failure' "$RUN_DIR/activation-trap-failure.log" \
    || fail "post-activation failure injection did not reach nginx -T"
write_certificate_identity "$RUN_DIR/certificate-identity.after-trap-failure.txt"
cmp "$RUN_DIR/certificate-identity.before-failures.txt" \
    "$RUN_DIR/certificate-identity.after-trap-failure.txt"
[[ "$(grep '^TLS_ENABLED=' "$ENV_FILE")" = 'TLS_ENABLED=true' ]] \
    || fail "unexpected post-activation failure changed the previously enabled TLS mode"
wait_for_https_restore "$RUN_DIR/https-after-trap-failure.txt" \
    "$RUN_DIR/https-after-trap-failure-errors.txt" \
    || fail "the previous TLS frontend was not restored by the EXIT trap"
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2>/dev/null | openssl x509 -out "$RUN_DIR/tls-after-trap-failure.pem"
openssl x509 -in "$RUN_DIR/tls-after-trap-failure.pem" -outform DER \
    -out "$RUN_DIR/tls-after-trap-failure.der"
cmp "$RUN_DIR/presented-leaf.der" "$RUN_DIR/tls-after-trap-failure.der"
openssl x509 -in "$RUN_DIR/tls-after-trap-failure.pem" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.after-trap-failure.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-served-fingerprint.after-trap-failure.txt"

if ACME_DIRECTORY_URL="https://pebble:14001/dir" \
    COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
    ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
    COMPOSE_BASE_FILE="" \
    COMPOSE_FILE="$COMPOSE_FILE" \
    COMPOSE_EXTRA_FILE="" \
    CERTBOT_CONF_DIR="$CONF_DIR" \
    CERTBOT_WWW_DIR="$WWW_DIR" \
    ./scripts/ops/certbot-init.sh > "$RUN_DIR/issuance-failure.log" 2>&1; then
    fail "certificate request failure injection unexpectedly succeeded"
else
    ISSUANCE_FAILURE_STATUS=$?
fi
cat "$RUN_DIR/issuance-failure.log"
[[ "$ISSUANCE_FAILURE_STATUS" -ne 0 ]] || fail "certificate request failure did not return nonzero"
grep -Fq 'Certificate issuance failed' "$RUN_DIR/issuance-failure.log" \
    || fail "certificate request failure was not observable in the script log"
write_certificate_identity "$RUN_DIR/certificate-identity.after-issuance-failure.txt"
cmp "$RUN_DIR/certificate-identity.before-failures.txt" \
    "$RUN_DIR/certificate-identity.after-issuance-failure.txt"
[[ "$(grep '^TLS_ENABLED=' "$ENV_FILE")" = 'TLS_ENABLED=true' ]] \
    || fail "failed certificate request changed the previously enabled TLS mode"
curl --silent --show-error --insecure --fail --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
    "https://$DOMAIN:$HTTPS_PORT/healthz" > "$RUN_DIR/https-after-issuance-failure.txt"
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2>/dev/null | openssl x509 -out "$RUN_DIR/tls-after-issuance-failure.pem"
openssl x509 -in "$RUN_DIR/tls-after-issuance-failure.pem" -outform DER \
    -out "$RUN_DIR/tls-after-issuance-failure.der"
cmp "$RUN_DIR/presented-leaf.der" "$RUN_DIR/tls-after-issuance-failure.der"
openssl x509 -in "$RUN_DIR/tls-after-issuance-failure.pem" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.after-issuance-failure.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-served-fingerprint.after-issuance-failure.txt"

compose stop pebble
if ITER202_FAIL_CERTBOT_RENEWAL=true \
    PATH="$RUN_DIR/test-bin:$PATH" \
    COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
    ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
    COMPOSE_BASE_FILE="" \
    COMPOSE_FILE="$COMPOSE_FILE" \
    COMPOSE_EXTRA_FILE="" \
    ./scripts/ops/certbot-renew.sh > "$RUN_DIR/renewal-failure.log" 2>&1; then
    fail "renewal failure injection unexpectedly succeeded"
else
    RENEWAL_FAILURE_STATUS=$?
fi
cat "$RUN_DIR/renewal-failure.log"
[[ "$RENEWAL_FAILURE_STATUS" -ne 0 ]] || fail "certificate renewal failure did not return nonzero"
grep -Fq 'Certificate renewal failed with exit status' "$RUN_DIR/renewal-failure.log" \
    || fail "certificate renewal failure was not observable in the script log"
grep -Fq 'Injected certbot renew launch failure' "$RUN_DIR/renewal-failure.log" \
    || fail "renewal failure injection did not reach the Certbot renewal command"
write_certificate_identity "$RUN_DIR/certificate-identity.after-renewal-failure.txt"
cmp "$RUN_DIR/certificate-identity.before-failures.txt" \
    "$RUN_DIR/certificate-identity.after-renewal-failure.txt"
[[ "$(grep '^TLS_ENABLED=' "$ENV_FILE")" = 'TLS_ENABLED=true' ]] \
    || fail "failed renewal changed the previously enabled TLS mode"
curl --silent --show-error --insecure --fail --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
    "https://$DOMAIN:$HTTPS_PORT/healthz" > "$RUN_DIR/https-after-renewal-failure.txt"
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2>/dev/null | openssl x509 -out "$RUN_DIR/tls-after-renewal-failure.pem"
openssl x509 -in "$RUN_DIR/tls-after-renewal-failure.pem" -outform DER \
    -out "$RUN_DIR/tls-after-renewal-failure.der"
cmp "$RUN_DIR/presented-leaf.der" "$RUN_DIR/tls-after-renewal-failure.der"
openssl x509 -in "$RUN_DIR/tls-after-renewal-failure.pem" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.after-renewal-failure.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-served-fingerprint.after-renewal-failure.txt"

for invalid_cert_name in . ..; do
    invalid_name_log="$RUN_DIR/cert-name-${invalid_cert_name//./dot}.log"
    invalid_name_root="$RUN_DIR/invalid-cert-name-${invalid_cert_name//./dot}"
    invalid_name_conf="$invalid_name_root/conf"
    invalid_name_www="$invalid_name_root/www"
    if CERT_NAME="$invalid_cert_name" \
        COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
        ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
        COMPOSE_BASE_FILE="" \
        COMPOSE_FILE="$COMPOSE_FILE" \
        COMPOSE_EXTRA_FILE="" \
        CERTBOT_CONF_DIR="$invalid_name_conf" \
        CERTBOT_WWW_DIR="$invalid_name_www" \
        ./scripts/ops/certbot-init.sh > "$invalid_name_log" 2>&1; then
        fail "CERT_NAME=$invalid_cert_name was not rejected"
    else
        INVALID_NAME_STATUS=$?
    fi
    [[ "$INVALID_NAME_STATUS" -eq 2 ]] \
        || fail "CERT_NAME=$invalid_cert_name did not return validation status 2"
    grep -Fq 'CERT_NAME may contain only letters, digits, dots, underscores, and hyphens.' \
        "$invalid_name_log" || fail "invalid CERT_NAME rejection was not observable"
    [[ ! -e "$invalid_name_conf" && ! -e "$invalid_name_www" ]] \
        || fail "invalid CERT_NAME=$invalid_cert_name created cert/webroot directories before rejection"
done
if find "$CONF_DIR" -maxdepth 1 -name '.certbot-init-*' -print -quit | grep -q .; then
    fail "invalid CERT_NAME created a certificate backup directory"
fi
openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" \
    -showcerts </dev/null 2>/dev/null | openssl x509 -out "$RUN_DIR/tls-after-invalid-cert-name.pem"
openssl x509 -in "$RUN_DIR/tls-after-invalid-cert-name.pem" -noout -fingerprint -sha256 \
    > "$RUN_DIR/tls-served-fingerprint.after-invalid-cert-name.txt"
cmp "$RUN_DIR/tls-served-fingerprint.before-failures.txt" \
    "$RUN_DIR/tls-served-fingerprint.after-invalid-cert-name.txt"

cat > "$ENV_FILE" <<EOF
SERVER_DOMAIN=127.0.0.1
CERT_NAME=iter202-d14-ip-only
CERTBOT_EMAIL=admin@example.test
ACME_DIRECTORY_URL=https://pebble:14000/dir
TLS_ENABLED=true
CERTBOT_CONF_DIR=$CONF_DIR
CERTBOT_WWW_DIR=$WWW_DIR
NGINX_IMAGE=$NGINX_IMAGE
CERTBOT_IMAGE=$CERTBOT_IMAGE
PEBBLE_IMAGE=$PEBBLE_IMAGE
CHALLTESTSRV_IMAGE=$CHALLTESTSRV_IMAGE
PEBBLE_API_CA=$PEBBLE_API_CA
EOF
chmod 600 "$ENV_FILE"
compose up -d --no-deps --force-recreate frontend
compose exec -T frontend nginx -t | tee "$RUN_DIR/ip-only-nginx-test.txt"
compose exec -T frontend nginx -T > "$RUN_DIR/ip-only-nginx-config.txt" 2>&1
compose logs --no-color frontend > "$RUN_DIR/ip-only-nginx.log" 2>&1
if grep -Fq 'listen 443 ssl;' "$RUN_DIR/ip-only-nginx-config.txt"; then
    fail "IP-only mode rendered a TLS listener"
fi
grep -Fq 'IP-only mode is HTTP-only' "$RUN_DIR/ip-only-nginx.log" \
    || fail "IP-only Nginx startup did not report HTTP-only behavior"
HTTP_PORT="$HTTP_HOST_PORT"
HTTPS_PORT="$HTTPS_HOST_PORT"
curl --silent --show-error --fail -H 'Host: 127.0.0.1' \
    "http://127.0.0.1:$HTTP_PORT/healthz" | tee "$RUN_DIR/ip-only-http-healthz.txt"
if curl --silent --show-error --insecure --fail --max-time 3 \
    "https://127.0.0.1:$HTTPS_PORT/healthz" > "$RUN_DIR/ip-only-https-healthz.txt" 2>&1; then
    fail "IP-only mode unexpectedly served HTTPS"
fi
if COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
    ENV_FILE_RELATIVE_PATH="$ENV_FILE" \
    COMPOSE_BASE_FILE="" \
    COMPOSE_FILE="$COMPOSE_FILE" \
    COMPOSE_EXTRA_FILE="" \
    CERTBOT_CONF_DIR="$CONF_DIR" \
    CERTBOT_WWW_DIR="$WWW_DIR" \
    ./scripts/ops/certbot-init.sh > "$RUN_DIR/ip-only-certbot-init.log" 2>&1; then
    fail "IP-only certificate request unexpectedly succeeded"
else
    IP_ONLY_STATUS=$?
fi
cat "$RUN_DIR/ip-only-certbot-init.log"
[[ "$IP_ONLY_STATUS" -ne 0 ]] || fail "IP-only certificate request did not return nonzero"
grep -Fq 'IP/localhost mode is HTTP-only' "$RUN_DIR/ip-only-certbot-init.log" \
    || fail "IP-only rejection was not explicit"

docker run --rm --network "${PROJECT_NAME}_default" --entrypoint nginx \
    -v "$PROJECT_ROOT/docker/nginx.prod.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$PROJECT_ROOT/docker/nginx.prod.locations.conf:/etc/nginx/conf.d/ai-investor-proxy.inc:ro" \
    "$NGINX_IMAGE" -t | tee "$RUN_DIR/static-http-nginx-test.txt"

compose logs --no-color --timestamps \
    | sed -E 's#(/\.well-known/acme-challenge/)[^[:space:]]+#\1[redacted]#g' \
    > "$RUN_DIR/compose-final.log" 2>&1
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' > "$RUN_DIR/containers-after.txt"
printf 'AC-D14 Pebble integration passed. Evidence: %s\n' "$RUN_DIR"
