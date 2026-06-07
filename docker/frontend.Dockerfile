# SummitFlow Web — multi-stage Docker build with standalone output
# Image: ghcr.io/elias-leslie/summitflow-web
# Port: 3001
# Requires: workspace packages (chat-ui) pre-packed as tarballs

# ── Stage 0: Dev Runtime ─────────────────────────────────────────
FROM node:20-slim AS dev

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /app

COPY frontend/ ./
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/
COPY .npmrc ./

RUN node -e "const fs = require('fs'); const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8')); pkg.dependencies = { ...pkg.dependencies, '@agent-hub/chat-ui': 'file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz', '@summitflow/notes-ui': 'file:/tmp/workspace-packages/summitflow-notes-ui-0.1.0.tgz' }; pkg.pnpm = pkg.pnpm || {}; pkg.pnpm.overrides = { ...(pkg.pnpm.overrides || {}), '@agent-hub/passport-client': 'file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz' }; pkg.pnpm.onlyBuiltDependencies = Array.from(new Set([...(pkg.pnpm.onlyBuiltDependencies || []), 'esbuild', 'sharp'])); fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));" && \
    CI=true pnpm install --no-frozen-lockfile

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3001"]

# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:20-slim AS builder

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /app

# Copy all frontend source
COPY frontend/ ./
COPY .npmrc ./

# Copy workspace package tarballs (built by pack-workspace-packages.sh)
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/

# Install dependencies and clean temp files in same layer
RUN node -e "const fs = require('fs'); const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8')); pkg.dependencies = { ...pkg.dependencies, '@agent-hub/chat-ui': 'file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz', '@summitflow/notes-ui': 'file:/tmp/workspace-packages/summitflow-notes-ui-0.1.0.tgz' }; pkg.pnpm = pkg.pnpm || {}; pkg.pnpm.overrides = { ...(pkg.pnpm.overrides || {}), '@agent-hub/passport-client': 'file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz' }; pkg.pnpm.onlyBuiltDependencies = Array.from(new Set([...(pkg.pnpm.onlyBuiltDependencies || []), 'esbuild', 'sharp'])); fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));" && \
    CI=true pnpm install --no-frozen-lockfile && \
    rm -rf /tmp/workspace-packages

# Build with standalone output, then prune pnpm store
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_URL=http://summitflow-api:8001
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ENV API_URL=${API_URL}
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
RUN pnpm build && pnpm store prune

# ── Stage 2: Runner ──────────────────────────────────────────────
FROM node:20-slim

RUN useradd -m -s /bin/bash appuser

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

COPY --chown=appuser:appuser --from=builder /app/.next/standalone ./
COPY --chown=appuser:appuser --from=builder /app/.next/static ./.next/static
COPY --chown=appuser:appuser --from=builder /app/public ./public

USER appuser

EXPOSE 3001

CMD ["node", "server.js"]
