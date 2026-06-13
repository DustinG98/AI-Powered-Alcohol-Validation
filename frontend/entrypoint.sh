#!/bin/sh
# Frontend entrypoint.
#
# Decides whether the HTTPS server block is active by checking
# whether the Let's Encrypt cert exists on disk. The cert path is
# baked at build time via the CERTBOT_DOMAIN build arg.
#
# On every start:
#   - If /etc/letsencrypt/live/${CERTBOT_DOMAIN}/fullchain.pem
#     exists, copy the prebuilt https.conf to
#     /etc/nginx/conf.d/https.conf. nginx's main config `include`s
#     it, so port 443 is served.
#   - If no cert, write an empty https.conf. nginx's `include` is
#     a no-op, so port 80 is served only.

set -eu

CERT_DIR="/etc/letsencrypt/live/${CERTBOT_DOMAIN:-}"
TARGET=/etc/nginx/conf.d/https.conf
SOURCE=/etc/nginx/conf-src/https.conf

if [ -n "${CERTBOT_DOMAIN:-}" ] && [ -f "${CERT_DIR}/fullchain.pem" ]; then
    echo "[frontend] Cert found — enabling HTTPS (${CERT_DIR}/fullchain.pem)."
    cp "${SOURCE}" "${TARGET}"
else
    echo "[frontend] No cert for ${CERTBOT_DOMAIN:-<unset>} — HTTP-only on :80."
    : > "${TARGET}"
fi

exec /docker-entrypoint.sh "$@"
