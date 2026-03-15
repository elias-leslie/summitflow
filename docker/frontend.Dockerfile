# SummitFlow Web — multi-stage Docker build with standalone output
# Image: ghcr.io/summitflow-solutions/summitflow-web
# Port: 3001
# Requires: workspace packages (chat-ui, push-client) pre-packed as tarballs

# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:20-slim AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy all frontend source
COPY frontend/ ./

# Copy workspace package tarballs (built by pack-workspace-packages.sh)
COPY docker/workspace-packages/*.tgz /tmp/workspace-packages/

# Replace workspace:* references with file: paths to tarballs
RUN sed -i 's|"@agent-hub/chat-ui": "workspace:\*"|"@agent-hub/chat-ui": "file:/tmp/workspace-packages/agent-hub-chat-ui-0.1.0.tgz"|g' package.json \
    && sed -i 's|"@agent-hub/push-client": "workspace:\*"|"@agent-hub/push-client": "file:/tmp/workspace-packages/agent-hub-push-client-0.1.0.tgz"|g' package.json

# Install dependencies
# Override transitive passport-client dep (chat-ui depends on it)
RUN echo '{"overrides":{"@agent-hub/passport-client":"file:/tmp/workspace-packages/agent-hub-passport-client-0.1.0.tgz"}}' > /tmp/override.json && \
    node -e "const p=require('./package.json'); const o=JSON.parse(require('fs').readFileSync('/tmp/override.json')); p.pnpm={...p.pnpm,...o}; require('fs').writeFileSync('package.json',JSON.stringify(p,null,2))" && \
    pnpm install --no-frozen-lockfile

# Build with standalone output
ENV NEXT_TELEMETRY_DISABLED=1
# API URLs for Next.js rewrites (baked at build time)
ARG API_URL=http://summitflow-api:8001
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ENV API_URL=${API_URL}
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
RUN pnpm build

# ── Stage 2: Runner ──────────────────────────────────────────────
FROM node:20-slim

# Create non-root user for runtime
RUN useradd -m -s /bin/bash appuser

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

# Copy standalone output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 3001

CMD ["node", "server.js"]
