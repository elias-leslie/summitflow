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
| Force close | `st close <id> --force` (bypass criteria) |
| List capabilities | `st capability list` |
| Show capability | `st capability show <id>` |
| Verify capability | `st capability verify <id>` |
| **End session** | See "Landing the Plane" in AGENTS.md |
| Start services | `bash ~/summitflow/scripts/start.sh` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Stop services | `bash ~/summitflow/scripts/shutdown.sh` |
| Check status | `bash ~/summitflow/scripts/status.sh` |
| Run tests | `cd ~/summitflow/backend && .venv/bin/pytest` |
| Type check | `cd backend && .venv/bin/mypy app/` |
| Validate all | `~/.claude/dev-tools/scripts/validate.sh` |
| Spec workflow | `/spec_it` (discovery, interview, spec output) |
| TDD workflow | `/tdd_it` (components, capabilities, tests) |
| Refactor workflow | `/refactor_it` (inventory, plan, execute) |

**Task Types:** `feature` (feature implementation), `bug`, `task`

**Global Hooks:** SessionStart (context injection), PreToolUse (git discipline), PostToolUse (observation capture), Stop (context monitoring)

**Session End (NON-NEGOTIABLE):** Commit impl → `st close` → `git pull --rebase && git push` (see AGENTS.md for full checklist)

---

## Rules (`.claude/rules/`)

| Rule | Purpose |
|------|---------|
| `issue-tracking.md` | **MANDATORY: Track ALL discovered bugs** |
| `architecture-coherence.md` | **MANDATORY: Anti-silo, DRY, holistic architecture** |
| `code-cleanliness.md` | **MANDATORY: Delete dead code, concise comments, no hoarding** |
| `explorer-architecture.md` | Explorer feature layer boundaries |
| `ui-backend-lockstep.md` | Backend changes need UI visibility |
| `service-management.md` | Systemd ops |
| `model-standards.md` | **MANDATORY: Use centralized model constants** |
| `interaction-style.md` | Communication style |
| `learned-patterns.md` | Auto-learned patterns from sessions |

---

## URLs

| Service | URL |
|---------|-----|
| Production (Cloudflare) | https://dev.summitflow.dev |
| Terminal (Cloudflare) | https://terminal.summitflow.dev |
| Terminal API (Cloudflare) | https://terminalapi.summitflow.dev |
| Local Frontend | http://localhost:3001 |
| Local Backend | http://localhost:8001 |
| Local Terminal Frontend | http://localhost:3002 |
| Local Terminal API | http://localhost:8002 |
| API Docs | http://localhost:8001/docs |

**Note:** Production URLs require Cloudflare Access auth. See `~/.claude/rules/cloudflare-access.md`.

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
- `capabilities` - TDD capability tracking (what must work)
- `artifacts` - Evidence (screenshots, logs)
- `vision_goals` - Project vision goals
- `vision_content` - Vision documentation

---

## API Conventions

- All endpoints scoped by `project_id`
- Timestamps in UTC (ISO 8601)
- IDs are prefixed (e.g., `task-abc123`, `FEAT-001`, `AC-001`)

---

## Context Memory

SummitFlow captures and learns from agent sessions automatically.

### Observation Capture
- **PostToolUse hook**: Captures observations from Write/Edit/Bash tool executions
- Observations stored in `observation_queue` table, processed async via Celery
- Extracted insights stored in `observations` table

### Context Injection
- **SessionStart hook**: Auto-injects recent context at session start
- Recent project activity, observations, and patterns shown on each new session

### Pattern Learning
- Patterns extracted from diary entries via reflection
- High-confidence patterns stored in `.claude/rules/learned-patterns.md`
- Applied automatically at session start

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /projects/{id}/context/index` | Context summary with item counts |
| `POST /projects/{id}/context/expand` | Expand specific context item |
| `GET /projects/{id}/context/session-start` | Context for session injection |

### Configuration
Memory features toggled per-project via agent config (Settings page):
- `memory_enabled` - Master switch
- `observations_enabled` - Tool observation capture
- `diary_enabled` - Session diary entries
- `patterns_enabled` - Pattern learning
- `context_injection_enabled` - Auto-inject at session start

---

## Autonomous Execution

SummitFlow can automatically execute low-risk tasks without human intervention.

### How It Works

1. **Explorer scans** identify refactoring candidates (high complexity files)
2. **Task generation** creates tasks with subtasks/steps and tier classification
3. **Work pickup** (every 30 min) claims eligible tasks
4. **Execution** runs via ImplementationExecutor with iteration loop
5. **Review gate** (every 30 min) validates results with Opus

### Tier Classification

| Tier | Model | Auto-Merge | Typical Tasks |
|------|-------|------------|---------------|
| 1 | Haiku | Yes | Small fixes, simple refactors |
| 2 | Sonnet | No | Medium complexity, multi-file |
| 3 | Opus | No | Complex changes, architectural |
| 4 | Human | Never | Security, breaking changes |

### Configuration

Settings via `PATCH /api/projects/{id}/autonomous/settings`:

```json
{
  "enabled": true,
  "frequency_minutes": 30,
  "auto_merge_tiers": [1],
  "task_types": ["auto-generated"]
}
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/projects/{id}/autonomous/settings` | GET | Get current settings |
| `/projects/{id}/autonomous/settings` | PATCH | Update settings |
| `/projects/{id}/autonomous/status` | GET | Status with metrics |
| `/projects/{id}/tasks/{task}/execute/start` | POST | Start execution |
| `/projects/{id}/tasks/{task}/execute/next` | POST | Execute next step |
| `/projects/{id}/tasks/{task}/execute/status` | GET | Get build_state |

### Celery Beat Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `autonomous_work_pickup` | 30 min | Claim and execute pending tasks |
| `review_pending_tasks` | 30 min | Opus review of completed work |
| `reset_expired_claims` | 10 min | Release stale task locks |

### Graduation Strategy

Tasks start with human review. As approval rate increases:
- 10+ tasks at >80% approval → reduce review frequency
- Tier 1 tasks can auto-merge after sustained success
- Tier 2+ always require human approval

### Monitoring Commands

```bash
# Watch autonomous activity in real-time
journalctl --user -u summitflow-celery -f | grep -E 'claimed|succeeded|failed|exhausted'

# Check for orphaned worktrees
ls /tmp/summitflow-worktrees/

# Recent autonomous activity
journalctl --user -u summitflow-celery --since "1 hour ago" | grep -E 'autonomous|work_pickup'

# Task status
st list --status running --json | jq '.tasks[] | {id, title, claimed_by}'
```

### Known Limitations

- Auto-generated tasks may be too complex for 5 iterations
- Task descriptions need specific acceptance criteria
- Pre-existing lint/type errors can block commits (agents may need SKIP=mypy,ruff)

### CLI Commands

| Command | Purpose |
|---------|---------|
| `/task_it <name>` | Create task with subtasks from planning session |
| `/do_it <task-id>` | Execute task via ImplementationExecutor |

### Standalone Execution (Fallback)

When SummitFlow services are unavailable or for standalone JSON-based execution:

| Command | Purpose |
|---------|---------|
| `/og_task_it` | Generate implementation.json from plan (no API) |
| `/og_do_it` | Execute from implementation.json (no API) |
| `/og_refactor_it` | Refactor workflow with local files |

**Use when:** SummitFlow backend is down, working offline, or need simpler file-based tracking.
**Location:** `~/.claude/commands/og_*.md`

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
| [docs/workflow-guide.md](docs/workflow-guide.md) | SummitFlow Capabilities/Tasks workflow |
| `~/.claude/docs/task-reference.md` | Tasks CLI reference (global) |
| `.claude/rules/` | Project-specific rules |
| `~/.claude/rules/` | Global rules (tasks-workflow, summitflow-vs-app) |

---

**Version**: 2.4.0 | **Updated**: 2025-12-31
