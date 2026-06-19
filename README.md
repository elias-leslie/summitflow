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

## Capabilities

SummitFlow is driven by **`st`**, a single CLI with ~36 command groups and ~266
subcommands over a FastAPI backend (~29 routers, ~280 routes), a Next.js operator
UI (~23 pages), and ~33 Hatchet workflows. Output is compact JSON by default, with
`--human` / `--compact` modes.

**Task lifecycle**

- `st pulse` (cross-agent coordination + preflight gate), `st claim`, `st context`,
  `st ready`, `st create`/`update`/`list`/`log`/`export`, `st done` (one-shot
  check + checkpoint + publish + closure), `st abandon` (rollback tracked changes).
- Tasks/subtasks/steps/dependencies with tiers, complexity, claim leasing, and
  evidence stored as JSONB (`verification_result`, `review_result`, `ai_review`).
- `st subtask`, `st dep`, `st note`, `st mandates`, `st critique` (second opinion),
  `st autocode` (queue a task for autonomous execution).

**Quality gates and code health**

- `st check` wraps ruff, types, pytest, biome, tsc, vitest, sqlfluff, squawk, and
  GitHub **CodeQL** alert checks, plus an isolated `cleanroom` run — with
  `--quick` / `--changed-only` / `--frontend-only` profiles.
- `st health` (quality-gate status), an LLM **auto-fix** agent with pattern memory,
  `radon` complexity assessment, and a self-healing monitor.
- `st graph` (Graphify topology + Fallow JS/TS audits) and `st search` (precision
  code search over symbols/endpoints/tables).

**Version control (jj-first)**

- `st commit` (st-owned commit/publish with check-gate and `--push`), `st jj` (full
  Jujutsu workflow incl. `revert` to roll back already-pushed work), `st git`
  (inspection), `st vcs doctor`/`reconcile` (cross-repo hygiene), `st checkpoints`,
  `st cleanup`.

**Services, runtime, and data**

- `st service` (rebuild = build + migrate + systemd-sync + health), `st runtime`
  (CPU/mem/GPU metrics), `st docker` (compose control + ephemeral test envs),
  `st db` (tables/schema/query/ddl/migrate + a Pgweb workbench), `st logs`,
  `st vm` (Proxmox test-VM lifecycle), `st setup`.

**Browser, UI, and evidence capture (the differentiator)**

- `st browser` (managed remote Chrome: open/check/screenshot/snapshot/eval, local-AI
  profile by default with optional Proxmox/VM isolation), `st ui` (X11 desktop
  control: screenshot, OCR, GIF, click/type/key), `st web` (Agent-Hub-routed web
  search/research/fetch), `st design` (AI or hand-authored HTML mockups + asset
  generation/import/critique/export), `st selection` (Aico selection bus).
- Autonomous runs capture page screenshots, route/health status, and console-error
  counts, and analyze screenshots with a vision model — attached to the task.

**Agents and AI (routed through Agent Hub)**

- `st agent` (real tool-loop sessions), `st agents` (agent definitions),
  `st complete` (completions with memory injection / thinking / streaming),
  `st claude` (Claude Code dispatch: task / batch / orchestrator), `st models`,
  `st prompt` (CRUD + revisions + YAML import/export), `st persona` (manage "Jenny"),
  `st memory` (save/search/tier/export), `st sessions` + `st session-events`
  (cross-project agent observability and ownership lanes), `st tools` (operator
  tool catalog + cost/governance telemetry), `st lease` (file-level coordination
  across parallel agents).

**Autonomous orchestration**

- `st autonomous` and an end-to-end pipeline (ideation → triage → planning →
  critique → execution → review → verification → escalation) on Hatchet, with
  scheduled work-pickup, task generation, tool governance, self-healing, and
  production smoke tests. `st refactor` regenerates refactor tasks from a scan.

**Backups, snapshots, and recovery**

- `st snap` / `snaps` / `recover` / `rollback` (Btrfs per-project snapshots;
  `recover` clones into a sibling project), and `st backup` (native archive engine
  with SMB and Veeam targets, `pg_dumpall` infra backups, scheduling, and
  restore-drill testing).

**Knowledge and coordination**

- `st wiki` (markdown vault), `st skills` (harness-neutral agent skills via symlink
  distribution), `st feedback` (agent feedback loop), `st pulsebrief`,
  `st projects`, and `st portfolio` (agent-facing analytics delegated to
  portfolio-ai).

## How it compares

Most agent tooling verifies work by trusting the agent's own narration —
*"I changed the files, the tests pass."* SummitFlow treats that as a claim to be
checked, not proof. Each task captures **evidence that the work actually ran** —
UI screenshots, check/test output, and route status — attached to the task and
visible to the operator.

| | SummitFlow | Temporal · Prefect · Hatchet | Devin · OpenHands |
|---|:---:|:---:|:---:|
| Purpose-built for AI-assisted dev work | ✅ | generic background jobs | ✅ |
| Proof-it-ran evidence captured per task | ✅ screenshots · checks · route status | generic logs/artifacts you populate | transcript / trajectory logs |
| Operator UI over projects **and** task lanes | ✅ | run-level only | ✅ |
| `st` CLI for tasks, checks, DB, backups, browser | ✅ | — | — |
| Self-hosted, no SaaS required | ✅ | ✅ | Devin is SaaS |

SummitFlow isn't a general workflow engine — it runs *on* one (Hatchet) and adds
the AI-dev task model, quality gates, and evidence capture on top.

> ⭐ If this approach resonates, a star helps other developers find it.

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
- `VAPID_*` values configure web-push notifications, which are delivered through the Agent Hub push service.
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
