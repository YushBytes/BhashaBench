# syntax=docker/dockerfile:1

# =============================================================================
# BhashaBench frontend image
# =============================================================================
# Node 22 LTS. The build context is `./frontend`, so paths below are relative
# to that directory.
FROM node:22-alpine AS base

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Manifests are copied first so the dependency layer is cached across
# source-only changes. `npm ci` requires the lockfile to be in sync.
COPY package.json package-lock.json ./
RUN npm ci

# -----------------------------------------------------------------------------
# Development target: full dependency set, hot reload.
# -----------------------------------------------------------------------------
FROM base AS development

COPY . .

# Compose mounts /app/.next as an anonymous volume so the container's build
# cache never mixes with one built on a Windows host. Docker seeds such a
# volume from the image's content at that path - and creates it root-owned
# if the path is absent. .next is excluded by .dockerignore, so it would be
# absent, and `next dev` running as `node` then fails with
# "EACCES: permission denied, mkdir '/app/.next/dev'". Creating the
# directory before the chown means the volume inherits node ownership.
#
# `node` is a non-root user that ships with the official image.
RUN mkdir -p /app/.next && chown -R node:node /app
USER node

EXPOSE 3000

# 0.0.0.0 so the port is reachable from the Docker host.
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

# -----------------------------------------------------------------------------
# Build stage: compile the production bundle.
# -----------------------------------------------------------------------------
FROM base AS builder

COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
# Production target: only what is needed to serve the built app.
# -----------------------------------------------------------------------------
FROM node:22-alpine AS production

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./

USER node

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
