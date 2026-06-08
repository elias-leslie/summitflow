# SummitFlow

Task orchestration and evidence capture for AI-assisted software development.

SummitFlow coordinates development work across projects: task intake, planning,
subtasks, quality gates, code-health scans, autonomous execution hooks, browser
checks, backups, and operator-visible evidence. It is designed for developers
running their own agent tooling, not as a hosted SaaS.

![SummitFlow — task orchestration and evidence capture for AI-assisted development](docs/images/summitflow-demo.gif)

*One control plane for your projects and agent lanes: the project dashboard, the agent task pipeline, live runtime and GPU health, and a built-in feedback loop.*

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13+-3776ab.svg)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-16-000.svg)](https://nextjs.org)

## What it does

- Tracks tasks, subtasks, steps, dependencies, status, and verification evidence.
- Provides a FastAPI backend and a Next.js operator UI for project/task state.
- Runs scheduled and event-driven workflows through Hatchet.
- Exposes the `st` CLI for task, project, check, database, backup, browser, and
  workflow operations.
- Integrates optionally with Agent Hub for routed AI-agent completions and shared
  agent memory.
- Captures UI/API smoke-test evidence when a browser runtime is configured.

## Requirements

Native development:

- Python 3.13+
- Node.js 20+
- pnpm 10+
- PostgreSQL 15+
- Redis
- Hatchet, for workflow/worker execution

Container development:

- Docker Engine with Docker Compose v2
- Node.js 20+, pnpm 10+, and `uv` for packing local workspace packages before
  Docker builds
- A sibling `agent-hub` checkout when building the SummitFlow + Agent Hub source
  stack locally

## Quickstart: local source stack with Docker Compose

This path builds SummitFlow and Agent Hub from adjacent local clones. It is the
simplest way to test the coupled public source release without private tooling.

```bash
git clone https://github.com/elias-leslie/summitflow.git
git clone https://github.com/elias-leslie/agent-hub.git
cd summitflow/docker/compose
cp .env.example .env
```

Edit `.env` and set at least these values:

```bash
POSTGRES_PASSWORD=change-me-postgres
SF_DB_PASSWORD=change-me-summitflow
AH_DB_PASSWORD=change-me-agent-hub
REDIS_PASSWORD=change-me-redis
HOST_HOME_PATH=/home/YOUR_USER
TAG=local
HATCHET_TAG=v0.84.0
AGENT_HUB_ENCRYPTION_KEY=<fernet-key>
AGENT_HUB_SECRET_KEY=<random-secret>
INTERNAL_SERVICE_SECRET=<random-secret>
SUMMITFLOW_CLIENT_ID=summitflow
SUMMITFLOW_REQUEST_SOURCE=summitflow
AGENT_HUB_DASHBOARD_CLIENT_ID=agent-hub-dashboard
AGENT_HUB_DASHBOARD_REQUEST_SOURCE=agent-hub-dashboard
```

Generate the two Agent Hub secrets with:

```bash
python - <<'PY'
import base64
import os
import secrets
print('AGENT_HUB_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())
print('AGENT_HUB_SECRET_KEY=' + secrets.token_urlsafe(32))
print('INTERNAL_SERVICE_SECRET=' + secrets.token_urlsafe(32))
PY
```

Pack the sibling Agent Hub workspace packages used by the SummitFlow frontend:

```bash
cd ../..
AGENT_HUB_ROOT=../agent-hub docker/scripts/pack-workspace-packages.sh docker/workspace-packages
cd docker/compose
```

Start infrastructure, generate the Hatchet token, then start the apps:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile summitflow --profile agent-hub \
  up -d postgres redis docker-socket-proxy hatchet-migrate hatchet-setup-config hatchet

COMPOSE_DIR=$PWD ../scripts/generate-hatchet-token.sh

docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile summitflow --profile agent-hub up -d --build
```

Open:

- SummitFlow UI: <http://localhost:3001>
- SummitFlow API health: <http://localhost:8001/health>
- Agent Hub UI: <http://localhost:3003>
- Agent Hub API health: <http://localhost:8003/health>

Stop the stack with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile summitflow --profile agent-hub down
```

Do not use `down --volumes` unless you intentionally want to delete local data.

## Native development

Copy the placeholder environment file and set real local service URLs:

```bash
cp .env.example .env.local
```

Backend:

```bash
cd backend
uv sync --all-extras --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Worker, in another shell:

```bash
cd backend
uv run python -m app.worker
```

Frontend, in another shell from the repo root. SummitFlow consumes a few
Agent Hub workspace packages, so pack them from the sibling Agent Hub checkout
before installing dependencies:

```bash
AGENT_HUB_ROOT=../agent-hub docker/scripts/pack-workspace-packages.sh docker/workspace-packages
pnpm install
pnpm --filter summitflow-frontend dev
```

CLI:

```bash
cd backend
uv run st --help
```

## Configuration

Start from [`.env.example`](.env.example). Required native values:

```bash
DATABASE_URL=postgresql://summitflow_app:PASSWORD@localhost:5432/summitflow
REDIS_URL=redis://localhost:6379/1
```

Optional values enable integrations:

- `AGENT_HUB_URL`, `SUMMITFLOW_CLIENT_ID`, `SUMMITFLOW_CLIENT_SECRET`, and
  `SUMMITFLOW_REQUEST_SOURCE` connect SummitFlow to Agent Hub.
- `HATCHET_CLIENT_TOKEN`, `HATCHET_CLIENT_HOST_PORT`, and
  `HATCHET_CLIENT_TLS_STRATEGY` enable Hatchet workers.
- `VAPID_*` values enable web-push notifications.
- `SMB_*` values enable the optional SMB backup target.
- Browser-runtime variables are optional; if absent, browser evidence features
  should fail clearly instead of crashing the core app.

## Architecture

```text
summitflow/
├── backend/       FastAPI app, SQLAlchemy models, Alembic migrations, CLI, tests
├── frontend/      Next.js operator UI, React components, API clients, tests
├── packages/      Shared workspace packages
├── docker/        Dockerfiles, compose stack, public source-stack bootstrap
├── scripts/       Utility scripts and service templates
└── .github/       Public CI and community templates
```

Main services:

- Frontend: `http://localhost:3001`
- Backend/API: `http://localhost:8001`
- PostgreSQL: task/project/state storage
- Redis: cache/background coordination
- Hatchet: workflow engine for scheduled and autonomous jobs
- Agent Hub: optional companion control plane for routed AI agents

## Testing, linting, type checks, and build

Install dependencies first. From a clean clone, pack the local Agent Hub
packages before `pnpm install`:

```bash
AGENT_HUB_ROOT=../agent-hub docker/scripts/pack-workspace-packages.sh docker/workspace-packages
pnpm install --frozen-lockfile
cd backend && uv sync --all-extras --dev
```

Backend checks:

```bash
cd backend
uv run ruff check .
uv run pytest
uv build
```

Frontend checks:

```bash
pnpm --filter summitflow-frontend lint
pnpm --filter summitflow-frontend exec tsc --noEmit
pnpm --filter summitflow-frontend exec vitest run
pnpm --filter summitflow-frontend build
```

Smoke test a running app:

```bash
curl -fsS http://localhost:8001/health
curl -fsS http://localhost:3001/ >/dev/null
```

## Optional and degraded behavior

SummitFlow can boot without provider API keys. Features that need Agent Hub,
Hatchet, web push, SMB backups, Docker socket access, or a browser runtime should
show missing-configuration behavior instead of exposing credentials or crashing
unrelated pages.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Security reporting is described in [SECURITY.md](SECURITY.md).
