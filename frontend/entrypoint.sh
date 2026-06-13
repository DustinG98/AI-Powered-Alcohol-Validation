#!/bin/sh
# Frontend entrypoint.
#
# On each start, pick the right nginx config based on whether the
# Let's Encrypt cert has been issued yet:
#   - cert present: use nginx.conf (HTTP + HTTPS) with the cert path
#     resolved at startup.
#   - no cert:      use nginx.local.conf (HTTP only) so nginx can
#     still start on port 80 and serve the ACME challenge.
#
# The certbot service is what causes the cert to appear, so this
# script effectively lets nginx and certbot bootstrap each other
# without manual intervention.

set -eu

CONF_DIR=/etc/nginx/conf.d
HTTPS_CONF=/etc/nginx/conf-src/default.conf.template
HTTP_CONF=/etc/nginx/conf-src/default.local.conf.template
LIVE_DIR="/etc/letsencrypt/live/${CERTBOT_DOMAIN:-}"

# Make sure we're starting from a clean slate so the right config wins.
# (The base image's envsubst step may have written other .conf files
# into this directory from previous runs; clear them all so nginx
# doesn't see duplicate upstream blocks or stale 443 listeners.)
rm -f "${CONF_DIR}/"*.conf

if [ -n "${CERTBOT_DOMAIN:-}" ] && [ -f "${LIVE_DIR}/fullchain.pem" ]; then
    echo "[frontend] Cert found at ${LIVE_DIR}/fullchain.pem — enabling HTTPS."
    if command -v envsubst >/dev/null 2>&1; then
        # envsubst on the official nginx image reads $VAR (not ${VAR})
        # and only substitutes variables exported in the container's
        # env. We pre-stage the template's $CERTBOT_DOMAIN here.
        envsubst "\$CERTBOT_DOMAIN" < "${HTTPS_CONF}" > "${CONF_DIR}/default.conf"
    else
        sed "s|\$CERTBOT_DOMAIN|${CERTBOT_DOMAIN}|g" "${HTTPS_CONF}" > "${CONF_DIR}/default.conf"
    fi
else
    echo "[frontend] No cert for ${CERTBOT_DOMAIN:-<unset>} yet — starting HTTP-only on :80 for ACME."
    if [ -f "${HTTP_CONF}" ]; then
        cp "${HTTP_CONF}" "${CONF_DIR}/default.conf"
    else
        echo "[frontend] ERROR: ${HTTP_CONF} not found; cannot start." >&2
        exit 1
    fi
fi

# Hand off to the base image's entrypoint, which runs envsubst on
# any remaining *.template files and then execs nginx.
exec /docker-entrypoint.sh "$@"
