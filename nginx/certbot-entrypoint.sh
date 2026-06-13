#!/bin/sh
# certbot entrypoint: obtain a cert on first run, renew on every
# subsequent run. Runs inside the `certbot` container.
#
# Required env vars:
#   CERTBOT_DOMAIN   e.g. label-check.example.com
#   CERTBOT_EMAIL    e.g. admin@example.com (used for Let's Encrypt notices)
#   CERTBOT_STAGING  optional; "true" to use Let's Encrypt staging env

set -eu

if [ -z "${CERTBOT_DOMAIN:-}" ] || [ -z "${CERTBOT_EMAIL:-}" ]; then
    # No cert config in this environment (e.g. local dev). Exit 0 so
    # the container stays stopped instead of restart-looping in
    # docker compose. Users who want TLS can set the env vars and
    # `docker compose up -d certbot` again.
    echo "[certbot] CERTBOT_DOMAIN / CERTBOT_EMAIL not set; nothing to do."
    exit 0
fi

CERT_DIR="/etc/letsencrypt/live/${CERTBOT_DOMAIN}"
WEBROOT="/var/www/certbot"
STAGING_FLAG=""
if [ "${CERTBOT_STAGING:-false}" = "true" ]; then
    STAGING_FLAG="--staging"
    echo "[certbot] Using Let's Encrypt STAGING environment (no real cert)."
fi

issue() {
    echo "[certbot] Requesting certificate for ${CERTBOT_DOMAIN}..."
    certbot certonly \
        --webroot \
        --webroot-path "${WEBROOT}" \
        --domain "${CERTBOT_DOMAIN}" \
        --email "${CERTBOT_EMAIL}" \
        --non-interactive \
        --agree-tos \
        --no-eff-email \
        ${STAGING_FLAG}
}

renew() {
    echo "[certbot] Renewing certificates..."
    certbot renew --webroot --webroot-path "${WEBROOT}" ${STAGING_FLAG}
}

if [ ! -d "${CERT_DIR}" ]; then
    issue
elif ! renew; then
    echo "[certbot] Renewal failed; attempting fresh issuance..."
    issue
fi

echo "[certbot] Done. Certs at ${CERT_DIR}."
echo "[certbot] Run 'docker compose restart frontend' so nginx picks up the new cert."

# Keep the container alive so scheduled restarts (or manual ones) can
# re-trigger issue/renew.
exec sleep infinity
