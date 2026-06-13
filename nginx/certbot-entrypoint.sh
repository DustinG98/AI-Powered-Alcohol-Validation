#!/bin/sh
# certbot entrypoint: obtain a cert on first run, renew on every subsequent
# run. Runs inside the `certbot` container.
#
# Required env vars:
#   CERTBOT_DOMAIN   e.g. label-check.example.com
#   CERTBOT_EMAIL    e.g. admin@example.com (used for Let's Encrypt notices)

set -eu

if [ -z "${CERTBOT_DOMAIN:-}" ] || [ -z "${CERTBOT_EMAIL:-}" ]; then
    echo "[certbot] CERTBOT_DOMAIN and CERTBOT_EMAIL must be set." >&2
    exit 1
fi

CERT_DIR="/etc/letsencrypt/live/${CERTBOT_DOMAIN}"
WEBROOT="/var/www/certbot"
STAGING=""
if [ "${CERTBOT_STAGING:-false}" = "true" ]; then
    STAGING="--staging"
    echo "[certbot] Using Let's Encrypt STAGING environment (no real cert)."
fi

attempt_issue() {
    echo "[certbot] Requesting certificate for ${CERTBOT_DOMAIN}..."
    certbot certonly \
        --webroot \
        --webroot-path "${WEBROOT}" \
        --domain "${CERTBOT_DOMAIN}" \
        --email "${CERTBOT_EMAIL}" \
        --non-interactive \
        --agree-tos \
        --no-eff-email \
        ${STAGING}
}

attempt_renew() {
    echo "[certbot] Renewing certificates..."
    certbot renew --webroot --webroot-path "${WEBROOT}" ${STAGING}
}

# Wait for the frontend (nginx) container to be ready to serve the
# ACME challenge. We poll /.well-known/acme-challenge/ until we get
# any 4xx response (i.e. nginx is up and answering).
echo "[certbot] Waiting for nginx to be reachable on port 80..."
for i in $(seq 1 30); do
    if wget -q -O- "http://frontend/.well-known/acme-challenge/probe" >/dev/null 2>&1; then
        echo "[certbot] nginx is up."
        break
    fi
    # wget returns 8 on 404; either way, nginx answering is what we need.
    if wget -q -S "http://frontend/.well-known/acme-challenge/probe" -O /dev/null 2>&1 | grep -q "HTTP/"; then
        echo "[certbot] nginx is up."
        break
    fi
    echo "[certbot] nginx not ready yet (attempt ${i}/30)..."
    sleep 2
done

if [ ! -d "${CERT_DIR}" ]; then
    attempt_issue
else
    # Existing cert present — try to renew. If renewal fails, fall
    # back to re-issuing in case the domain or account changed.
    if ! attempt_renew; then
        echo "[certbot] Renewal failed; attempting fresh issuance..."
        attempt_issue
    fi
fi

# Reload nginx so it picks up the (possibly new) certs. We use the
# docker network DNS name `frontend` (the nginx container). The
# certbot container needs the docker CLI; the simplest cross-platform
# trick is to send a SIGHUP via docker.sock if mounted, but a more
# portable approach is to use the `nginx -s reload` over a shared
# volume. The setup below just relies on docker-compose to restart
# the frontend on cert change (via a small `nginx-reload` container
# not included here) — for this prototype, restarting `docker compose
# up -d frontend` is the documented step after first issuance.

echo "[certbot] Done. Certs are at ${CERT_DIR}."
echo "[certbot] If this was the first issuance, restart nginx so it"
echo "[certbot] picks up the new certs:"
echo "[certbot]   docker compose restart frontend"

# Keep the container alive long enough to be inspected via `docker logs`
# and so that scheduled re-runs (e.g. cron sidecar) can invoke it.
# An infinite sleep here is the standard certbot-in-docker pattern.
exec sleep infinity
