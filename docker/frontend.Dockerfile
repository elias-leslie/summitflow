# SummitFlow Web: install the same workspace manifest, lock and package artifacts as CI.
FROM node:24-slim AS dependencies
RUN corepack enable && corepack prepare pnpm@10.28.0 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY frontend/ ./frontend/
COPY packages/notes-ui/ ./packages/notes-ui/
COPY docker/workspace-packages/*.tgz ./docker/workspace-packages/
RUN CI=true pnpm install --frozen-lockfile
RUN pnpm --filter @summitflow/notes-ui build

FROM dependencies AS dev
WORKDIR /workspace/frontend
ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3001"]

FROM dependencies AS builder
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_URL=http://summitflow-api:8001
ARG AGENT_HUB_API_URL=http://agent-hub-api:8003
ENV API_URL=${API_URL}
ENV AGENT_HUB_API_URL=${AGENT_HUB_API_URL}
RUN pnpm --filter summitflow-frontend build

FROM node:24-slim AS runner
RUN useradd -m -s /bin/bash appuser
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
COPY --chown=appuser:appuser --from=builder /workspace/frontend/.next/standalone ./
COPY --chown=appuser:appuser --from=builder /workspace/frontend/.next/static ./frontend/.next/static
COPY --chown=appuser:appuser --from=builder /workspace/frontend/public ./frontend/public
USER appuser
EXPOSE 3001
CMD ["node", "frontend/server.js"]
