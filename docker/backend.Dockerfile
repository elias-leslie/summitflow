# SummitFlow API — multi-stage Docker build
# Image: ghcr.io/elias-leslie/summitflow-api
# Port: 8001
# Worker: same image with CMD ["python", "-m", "app.worker"]

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (cache-friendly layer)
COPY backend/pyproject.toml backend/uv.lock ./
COPY docker/workspace-packages/*.whl /tmp/wheels/

# Install deps and clean caches in same layer
RUN uv export --frozen --no-dev --no-editable --format requirements-txt \
      --no-header > requirements.txt && \
    sed -i '/^\.$/d; /agent-hub-client$/d; /^\.\.\//d' requirements.txt && \
    uv venv .venv && \
    uv pip install --python .venv/bin/python \
      -r requirements.txt /tmp/wheels/agent_hub_client-*.whl && \
    rm -rf /tmp/wheels /root/.cache/uv /root/.cache/pip requirements.txt

# Copy application source
COPY backend/app ./app
COPY backend/cli ./cli
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm

# Runtime deps only: curl (healthcheck), git+ssh (Git Operations page),
# Docker CLI (Docker dashboard API), smbclient (SMB mounts feature)
# Note: nodejs and postgresql-client removed — not needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git openssh-client smbclient gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user before COPY --chown, configure git for mounted repos
RUN useradd -m -s /bin/bash appuser \
    && git config --global --add safe.directory '*' \
    && mkdir -p /etc/ssh && ssh-keyscan github.com >> /etc/ssh/ssh_known_hosts 2>/dev/null

WORKDIR /app

# Copy venv and app from builder (--chown avoids separate chown layer)
COPY --chown=appuser:appuser --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser --from=builder /app/app ./app
COPY --chown=appuser:appuser --from=builder /app/cli ./cli
COPY --chown=appuser:appuser --from=builder /app/alembic.ini ./
COPY --chown=appuser:appuser --from=builder /app/alembic ./alembic

RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY --chmod=755 docker/scripts/entrypoint-backend.sh /entrypoint.sh

USER appuser

EXPOSE 8001
ENV PORT=8001

ENTRYPOINT ["/entrypoint.sh"]
