# SummitFlow

Task management and orchestration platform for AI-assisted software development.

## Overview

SummitFlow manages the full lifecycle of development tasks across multiple software projects. It provides task creation, planning, autonomous execution, code health analysis, quality gates, and evidence capture. An AI agent pipeline handles triage, planning, execution, and review of tasks via the Hatchet workflow engine.

Key capabilities:
- **Task Management** - Tasks with subtasks, steps, verification gates, and dependency tracking
- **Autonomous Execution** - AI-driven task execution pipeline (triage, plan, execute, review)
- **Code Health** - Codebase analysis, metrics, and automated refactoring suggestions
- **Quality Gates** - Verification-based step completion with citation requirements
- **Evidence Capture** - Screenshots, console logs, and network activity for feature verification
- **Project Monitoring** - Sitemap discovery, endpoint health checks, and system monitoring

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.13+, SQLAlchemy 2.0, Pydantic 2 |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| Database | PostgreSQL 15+ (psycopg 3, connection pooling) |
| Caching | Redis |
| Workflows | Hatchet (pipeline, scheduled, utility workflows) |
| CLI | Typer + Rich (`st` command) |
| Quality | Ruff, Ty, pytest, Vitest, Biome |

## Architecture

```
summitflow/
├── backend/
│   ├── app/
│   │   ├── api/           # REST endpoints
│   │   ├── services/      # Business logic
│   │   │   ├── autonomous/    # Autonomous execution
│   │   │   ├── code_health/   # Code health analysis
│   │   │   ├── explorer/      # Code exploration
│   │   │   ├── quality_gate/  # Quality gate logic
│   │   │   └── self_healing/  # Self-healing services
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic models
│   │   ├── storage/       # Database access layer
│   │   ├── tasks/         # Background task definitions
│   │   └── workflows/     # Hatchet workflow definitions
│   ├── cli/               # st CLI (task management)
│   │   ├── commands/      # Subcommands
│   │   └── lib/           # CLI utilities
│   └── tests/
├── frontend/
│   ├── app/               # Pages (App Router)
│   │   ├── projects/[id]/ # Project detail pages
│   │   ├── backups/       # Backup management
│   │   └── git/           # Git operations
│   ├── components/        # React components
│   │   ├── tasks/         # Task management UI
│   │   ├── kanban/        # Kanban board
│   │   ├── explorer/      # Code explorer
│   │   ├── health/        # Health monitoring
│   │   ├── execution/     # Task execution UI
│   │   └── evidence/      # Evidence capture modal
│   └── lib/               # API clients, hooks, utilities
├── scripts/               # Shared scripts (canonical source)
│   ├── rebuild.sh         # Build and restart services
│   ├── backup.sh          # Database backup to NAS
│   ├── restore.sh         # Database restore
│   ├── dev-tools.sh       # Quality tool wrapper (dt CLI)
│   ├── commit.sh          # Multi-repo commit handler
│   └── systemd/           # Systemd service definitions
└── tasks/                 # Task specifications and state
```

## CLI (`st`)

SummitFlow includes a Typer-based CLI for task management:

```bash
st list                        # List tasks
st -P summitflow create --plan plan.json  # Create execution-ready task (requires -P)
st -P summitflow capture bug "Fix login bug"  # Capture a lightweight bug kernel
st -P summitflow capture idea "Add SSO"       # Capture a lightweight idea kernel
st claim <task-id>             # Claim task (creates checkpoint checkpoint)
st context                     # Show current task details
st step pass <subtask> <step>  # Mark step as passed
st subtask pass <subtask-id>   # Pass a subtask
st done <task-id>              # Complete task (merge + cleanup)
st abandon <task-id>           # Abandon task
st autocode <task-id>          # Queue for autonomous execution
st checkpoints                 # List active checkpoints
st memory search <query>       # Search memory system
```

## Hatchet Workflows

### Pipeline (task lifecycle)
`triage_wf` → `plan_wf` → `execute_wf` → `review_wf` → `merge_cleanup_wf`

### Scheduled
| Workflow | Schedule | Description |
|----------|----------|-------------|
| `code_health_wf` | Daily 2 AM | Code health scan |
| `deep_scan_wf` | Sunday 3 AM | Deep analysis |
| `scan_projects_wf` | Every 6h | Project scanning |
| `self_healing_wf` | Every 15m | Auto-healing |
| `work_pickup_wf` | Every 2h | Autonomous work pickup |
| `task_generation_wf` | Hourly | Routine upkeep signal discovery and autonomous task routing |
| `scheduled_backups_wf` | 30m past hour | Backup scheduling |
| `stale_cleanup_wf` | Daily 4 AM | Stale task cleanup |

### Utility
Backup create/restore, PR review, enrichment, checkpoint cleanup, schema tasks.

## Ports

| Service | Port |
|---------|------|
| Frontend (Next.js) | 3001 |
| Backend (FastAPI) | 8001 |

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 20+
- PostgreSQL 15+
- Redis

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload --port 8001

# Start Hatchet worker (separate A-Term)
python -m app.worker
```

### Frontend

```bash
cd frontend
pnpm install
pnpm run dev
```

### CLI

```bash
pip install -e ".[dev]"   # CLI included in backend package
st --help
```

### Environment

Runtime settings are read from `~/.env.local` by default. Use
[`.env.example`](.env.example) as the placeholder reference for local setup.
Only `DATABASE_URL` is required for the backend to boot; the rest are optional
overrides for local integrations and background services.

### Agent Tooling Bootstrap

To provision the shared local agent environment on a new machine, run:

```bash
bash ~/summitflow/scripts/setup-agent-tooling.sh
```

That bootstrap installs the Codex CLI and Claude Code, clones or updates the
shared `codex-config` and `claude-config` repos, installs the Codex wrapper from
the config repo, and enables the supporting user services and timers.

### Register a Project

```bash
curl -X POST http://localhost:8001/api/projects \
  -H "Content-Type: application/json" \
  -d '{"id": "my-project", "name": "My Project", "base_url": "http://localhost:8000"}'
```

## Database

35+ tables including tasks, subtasks, steps, projects, events, explorer entries, backups, quality checks, notifications, and agent sessions. Schema managed via Alembic migrations.

## Shared Scripts

SummitFlow `scripts/` is the canonical source for shared development scripts. Other projects (portfolio-ai, agent-hub, a-term) symlink to these:

- `rebuild.sh` - Build and restart services (auto-detects Docker vs native)
- `backup.sh` - Database + files backup to SMB share
- `restore.sh` - Restore from local or SMB backup
- `dev-tools.sh` - Quality tool wrapper (`dt` CLI for ruff, types, pytest, biome)
- `commit.sh` - Multi-repo commit handler
- `setup-agent-tooling.sh` - Bootstrap Claude Code, Codex CLI, config repos, and observability services

## Services

Current default runtime is hybrid:

- First-party apps run as `systemd --user` services
- Shared infra (`postgres`, `redis`, `hatchet`) stays in Docker
- Full Docker app stacks remain available for parity and container checks

```bash
scripts/rebuild.sh            # Full rebuild and restart (auto-detects Docker)
scripts/rebuild.sh --restart  # Restart only (no rebuild)
scripts/rebuild.sh --status   # Check service health
```

## Testing

```bash
# Backend
cd backend
pytest tests/ -v --cov=app

# Frontend
cd frontend
pnpm run test

# Quality checks
dt --check            # Full quality check (ruff, types, biome, pytest)
dt -q -d              # Quick check on changed files
```

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Security

Please report suspected vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## Commercial

Commercial use is permitted under the Apache 2.0 license.

For commercial support, custom work, partnership discussions, or private
licensing for future versions, contact `summitflow42@gmail.com`.
