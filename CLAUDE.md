# CLAUDE.md

SummitFlow - AI-assisted development platform.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st --compact ready` |
| Claim work | `st update <id> --status running` |
| Complete | `st close <id> --reason "Done"` |
| Start services | `bash ~/summitflow/scripts/restart.sh` |
| Rebuild frontend | `bash scripts/rebuild-frontend.sh` |
| Run tests | `cd backend && .venv/bin/pytest` |
| Type check | `cd backend && .venv/bin/mypy app/` |
| Logs | `journalctl --user -u summitflow-backend -f` |
| DB CLI | `source ~/.env.local && psql "$DATABASE_URL"` |

---

## URLs

| Service | URL |
|---------|-----|
| Production | https://dev.summitflow.dev |
| Local Frontend | http://localhost:3001 |
| Local Backend | http://localhost:8001 |
| API Docs | http://localhost:8001/docs |

---

## Cloudflare Access

Production URLs require auth headers. Credentials: `~/.cloudflare-access`

```bash
source ~/.cloudflare-access && curl -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" https://dev.summitflow.dev/api/health
```

---

## Core Rules

1. **Backend changes need UI visibility** - Complete the vertical slice
2. **Track discovered bugs immediately** - `st create "Fix: X" -t bug`
3. **SummitFlow vs App** - Dev tooling goes in SummitFlow. User-facing functionality stays in the app.
4. **Consolidate over create** - Check for existing implementations before writing new code

---

## Development Workflow

```
/plan_it → st task import → /do_it
```

| Command | Purpose |
|---------|---------|
| `/plan_it <desc>` | Plan task with adaptive interview → plan.json |
| `st task verify <file>` | Validate plan against schema |
| `st task import <file>` | Create task from plan.json |
| `/do_it <task-id>` | Execute subtasks, commit, close task |
| `/commit_it` | Quality gates (pytest, lint) then commit |

---

## Essential Commands

### st (SummitFlow Tasks)

```bash
# Core workflow (use --compact for reads, 80%+ token reduction)
st --compact ready                    # Tasks ready to work on
st update <id> --status running       # Claim task
st close <id> --reason "Done"         # Complete task

# Create
st create "Title" -t task -p 2 -d "Description"
st bug "Fix: X" -p 2                  # Shorthand for -t bug

# Subtasks & Steps
st --compact subtask list <task-id>   # List subtasks
st step pass <task-id> <subtask-id> <step-number>  # Mark step passed
st subtask pass <task-id> <subtask-id>             # Mark subtask passed
```

### member-dis (Memory) - DISABLED

**Status:** Memory system disabled pending migration to standalone system.

**What's DISABLED:**
- Pattern persistence (nothing saved between sessions)
- `member-dis search/expand/index` commands return empty
- Memory-based suggestions at session start
- Diary aggregation and reflection generation
- Embedding updates

**What's ACTIVE (fire-and-forget):**
- Observation capture (PostToolUse hook still runs)
- API endpoints exist but return empty results

**Configuration:**
- **To re-enable:** Set `MEMORY_SYSTEM_ENABLED=true` in `backend/.env`, restart services
- **Migration plan:** `tasks/memory-system/memory-system-requirements.md`
- **Disabled since:** 2026-01-06

---

## Additional Resources

- **Model Constants:** See `~/.claude/rules/model-standards.md` (never hardcode model strings)
- **Commands vs Skills:** See `~/.claude/rules/commands-vs-skills.md` (commands are `/invoked`, skills auto-trigger)
- **Task Planning:** Use `/plan_it` for new work, `/do_it` for execution
- **Issue Tracking:** Use `st create "Fix: X" -t bug` for discovered bugs
- **Rules Taxonomy:** See `/optimize_rules` command for canonical file structure (behavior, process, reference, domain)
- **Memory System:** DISABLED - see `backend/.env` (`MEMORY_SYSTEM_ENABLED=false`)
- **Permissions:** Intentionally empty in settings.json - bypass mode used. Do NOT suggest adding permission rules.

---

**Version**: 4.0.0
