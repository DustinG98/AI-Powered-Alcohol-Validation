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

# The default nginx site is mounted read-only at runtime via compose, so
# we don't need to delete it here — but it doesn't hurt to be explicit
# in case anyone runs the image standalone.
RUN rm -f /etc/nginx/conf.d/default.conf

# Healthcheck against the container's own /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://127.0.0.1/healthz || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
