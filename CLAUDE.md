# CLAUDE.md

SummitFlow - AI-assisted software development platform.

**Read [AGENTS.md](AGENTS.md) for task tracking and workflow.**

---

## MANDATORY: Discovered Issues = Immediate Tasks

**When you encounter ANY pre-existing bug/error during work:**
1. Review ALL open tasks: `st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'`
2. Create if missing: `st create "Fix: <desc>" -t bug -p 2 -l "complexity:small,domains:backend"`
3. Link to parent: `st dep add <new-id> <parent-id> --type discovered-from`

**Do NOT filter by keywords. Scan the FULL task list. No exceptions.**

**Task Reference:** See `~/.claude/docs/task-reference.md` for valid types, labels, and commands.
See `.claude/rules/issue-tracking.md` for full protocol.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete work | `st close <id> --reason "Done"` |
| **End session** | See "Landing the Plane" in AGENTS.md |
| Start services | `bash ~/summitflow/scripts/start.sh` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Stop services | `bash ~/summitflow/scripts/shutdown.sh` |
| Check status | `bash ~/summitflow/scripts/status.sh` |
| Run tests | `cd ~/summitflow/backend && .venv/bin/pytest` |

**Session End (NON-NEGOTIABLE):** Commit impl → `st close` → `git pull --rebase && git push` (see AGENTS.md for full checklist)

---

## Rules (5 files in `.claude/rules/`)

| Rule | Purpose |
|------|---------|
| `issue-tracking.md` | **MANDATORY: Track ALL discovered bugs** |
| `architecture-coherence.md` | **MANDATORY: Anti-silo, DRY, holistic architecture** |
| `ui-backend-lockstep.md` | Backend changes need UI visibility |
| `service-management.md` | Systemd ops |
| `interaction-style.md` | Communication style |

---

## URLs

| Service | URL |
|---------|-----|
| Production (Cloudflare) | https://dev.summitflow.dev |
| Local Frontend | http://localhost:3001 |
| Local Backend | http://localhost:8001 |
| API Docs | http://localhost:8001/docs |

---

## Service Management

Services run via `systemctl --user` (user-mode systemd).

```bash
# Check specific service
systemctl --user status summitflow-backend
systemctl --user status summitflow-frontend

# View logs
journalctl --user -u summitflow-backend -f
journalctl --user -u summitflow-frontend -f

# Manual control
systemctl --user start summitflow-backend
systemctl --user stop summitflow-frontend
systemctl --user restart summitflow-backend
```

---

## Project Structure

```
summitflow/
├── backend/
│   ├── app/
│   │   ├── api/       # FastAPI routers
│   │   ├── services/  # Business logic
│   │   ├── storage/   # Database access
│   │   └── main.py    # FastAPI app
│   └── .venv/         # Python virtual environment
├── frontend/
│   ├── app/           # Next.js pages
│   ├── components/    # React components
│   └── lib/           # API client, utilities
├── .claude/           # Claude configuration
│   ├── rules/         # Mandatory rules
│   ├── docs/          # Reference documentation
│   └── skills/        # Domain skills
└── scripts/
    ├── systemd/       # Service files
    └── *.sh           # Control scripts
```

---

## Database

PostgreSQL database: `summitflow`

Core tables:
- `projects` - Registered target applications
- `tasks` - Issue tracking and auto-agent tasks
- `task_dependencies` - Dependency relationships between tasks
- `explorer_entries` - Unified explorer data (files, tables, tasks, endpoints)
- `explorer_relationships` - Cross-entity relationships
- `feature_capabilities` - Feature tracking
- `artifacts` - Evidence (screenshots, logs)
- `vision_goals` - Project vision goals
- `vision_content` - Vision documentation

---

## API Conventions

- All endpoints scoped by `project_id`
- Timestamps in UTC (ISO 8601)
- IDs are prefixed (e.g., `task-abc123`, `FEAT-001`, `AC-001`)

---

## First-Time Setup

```bash
# 1. Install and enable services (run once)
bash ~/summitflow/scripts/setup-services.sh

# 2. Start services
bash ~/summitflow/scripts/start.sh

# 3. Access at https://dev.summitflow.dev
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | Task tracking, workflow |
| [docs/workflow-guide.md](docs/workflow-guide.md) | SummitFlow Features/Tasks workflow |
| `~/.claude/docs/task-reference.md` | Tasks CLI reference (global) |
| `.claude/rules/` | Project-specific rules |
| `~/.claude/rules/` | Global rules (tasks-workflow, summitflow-vs-app) |

---

**Version**: 2.0.0 | **Updated**: 2025-12-19
