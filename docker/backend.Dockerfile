# SummitFlow API — multi-stage Docker build
# Image: ghcr.io/summitflow-solutions/summitflow-api
# Port: 8001
# Worker: same image with CMD ["python", "-m", "app.worker"]

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock ./

# Copy pre-built agent-hub-client wheel (local path dep won't resolve in Docker)
COPY docker/workspace-packages/*.whl /tmp/wheels/

# Install deps: export requirements, swap local path dep with wheel, install
RUN uv export --frozen --no-dev --no-editable --format requirements-txt \
      --no-header > requirements.txt && \
    # Remove the local path line for agent-hub-client
    sed -i '/^\.$/d; /agent-hub-client$/d; /^\.\.\//d' requirements.txt && \
    # Create venv and install from requirements + wheel
    uv venv .venv && \
    uv pip install --python .venv/bin/python \
      -r requirements.txt /tmp/wheels/agent_hub_client-*.whl

# Copy application source
COPY backend/app ./app
COPY backend/cli ./cli
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm

# Install curl for healthchecks, git for Git Operations page,
# Docker CLI (official) for Docker dashboard API,
# Node.js LTS for frontend quality gates (biome, tsc via npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git jq smbclient gnupg openssh-client \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends \
        docker-ce-cli postgresql-client-16 nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/cli ./cli
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/alembic ./alembic

# Ensure venv binaries are on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Create non-root user for runtime
RUN useradd -m -s /bin/bash appuser \
    && chown -R appuser:appuser /app

# Allow git to operate on mounted host repos (different UID)
RUN git config --global --add safe.directory '*'

# Copy and use entrypoint script
COPY docker/scripts/entrypoint-backend.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8001
ENV PORT=8001

ENTRYPOINT ["/entrypoint.sh"]
