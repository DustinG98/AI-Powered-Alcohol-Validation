# syntax=docker/dockerfile:1.6

# =============================================================================
# Stage 1: build the Vite production bundle.
# =============================================================================
FROM node:20-alpine AS build

WORKDIR /app

# Install deps with the lockfile when present.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Build args are the only way to inject VITE_* values at build time
# (Vite inlines them into the bundle). Default to the local backend.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY . .

RUN npm run build

# =============================================================================
# Stage 2: serve the static bundle with nginx.
# =============================================================================
FROM nginx:1.27-alpine

# Replace the default nginx site bundle with the Vite build output.
# Vite builds into /app/dist in the build stage (the default `outDir`).
COPY --from=build /app/dist /usr/share/nginx/html

# Cert domain is baked in at build time. Default to a sentinel that
# produces an obviously-invalid cert path, so the image still builds
# (and still runs) without a real cert. The compose-driven local-dev
# flow also writes an empty https.conf via entrypoint.sh, which
# shields the rendered path from nginx entirely.
ARG CERTBOT_DOMAIN=_unset
# https.conf contains a literal $CERTBOT_DOMAIN token; substitute it
# at build time and install the rendered file. The entrypoint
# overwrites this with an empty file when no cert is on disk yet.
COPY nginx/https.conf /etc/nginx/conf-src/https.conf
RUN sed -i "s|\$CERTBOT_DOMAIN|${CERTBOT_DOMAIN}|g" /etc/nginx/conf-src/https.conf

# Install the base nginx config into the image's templates dir so the
# base image's envsubst step renders it. The include of
# /etc/nginx/conf.d/https.conf is always present in nginx.conf, so
# envsubst has nothing to substitute at runtime.
COPY nginx/nginx.conf /etc/nginx/templates/default.conf.template

# Entry point: on every start, copy the prebuilt https.conf (or write
# an empty placeholder) into /etc/nginx/conf.d/ based on whether the
# Let's Encrypt cert is on disk. See entrypoint.sh.
COPY entrypoint.sh /usr/local/bin/frontend-entrypoint.sh
RUN chmod +x /usr/local/bin/frontend-entrypoint.sh

# Healthcheck against the container's own /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://127.0.0.1/healthz || exit 1

EXPOSE 80

ENTRYPOINT ["/usr/local/bin/frontend-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
