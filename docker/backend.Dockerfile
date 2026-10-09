# SummitFlow API — multi-stage Docker build
# Image: ghcr.io/elias-leslie/summitflow-api
# Port: 8001
# Worker: same image with CMD ["python", "-m", "app.worker"]

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

WORKDIR /app/backend

# Copy dependency files first (cache-friendly layer)
COPY backend/pyproject.toml backend/uv.lock ./
COPY docker/workspace-packages/ /app/docker/workspace-packages/

# Validate exact local release archives before syncing; never accept a rebuilt
# same-name wheel or an artifact download as a substitute for the locked hash.
RUN python3 - <<'PY'
import hashlib
import tomllib
from pathlib import Path

lock = tomllib.loads(Path("uv.lock").read_text())
count = 0
for package in lock["package"]:
    source = package["source"].get("path", "")
    if not source.endswith(".whl"):
        continue
    wheel = Path(source)
    if source != "../docker/workspace-packages/" + wheel.name:
        raise SystemExit("Unexpected local wheel path in lock")
    expected = [{"filename": wheel.name, "hash": "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()}]
    if package.get("wheels") != expected:
        raise SystemExit("Locked local wheel hash differs: " + wheel.name)
    count += 1
if count == 0:
    raise SystemExit("No locked local release wheels")
PY

# Install deps and clean caches in same layer
RUN uv sync --frozen --no-dev --no-editable --no-install-project \
    && rm -rf /root/.cache/uv /root/.cache/pip

# Copy application source
COPY backend/app ./app
COPY backend/cli ./cli
COPY backend/monitor_control ./monitor_control
COPY backend/monitor_extended ./monitor_extended
COPY backend/monitor_observe ./monitor_observe
COPY backend/monitor_reader ./monitor_reader
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
COPY --chown=appuser:appuser --from=builder /app/backend/.venv /app/backend/.venv
COPY --chown=appuser:appuser --from=builder /app/backend/app ./app
COPY --chown=appuser:appuser --from=builder /app/backend/cli ./cli
COPY --chown=appuser:appuser --from=builder /app/backend/monitor_control ./monitor_control
COPY --chown=appuser:appuser --from=builder /app/backend/monitor_extended ./monitor_extended
COPY --chown=appuser:appuser --from=builder /app/backend/monitor_observe ./monitor_observe
COPY --chown=appuser:appuser --from=builder /app/backend/monitor_reader ./monitor_reader
COPY --chown=appuser:appuser --from=builder /app/backend/alembic.ini ./
COPY --chown=appuser:appuser --from=builder /app/backend/alembic ./alembic

RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY --chmod=755 docker/scripts/entrypoint-backend.sh /entrypoint.sh

USER appuser

EXPOSE 8001
ENV PORT=8001

ENTRYPOINT ["/entrypoint.sh"]
