# CLAUDE.md

SummitFlow - AI-assisted development platform.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete | `st close <id> --reason "Done"` |
| Start services | `bash ~/summitflow/scripts/restart.sh` |
| Run tests | `cd backend && .venv/bin/pytest` |
| Type check | `cd backend && .venv/bin/mypy app/` |
| Logs | `journalctl --user -u summitflow-backend -f` |

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

## Essential Commands

### st (SummitFlow Tasks)

```bash
# Core workflow
st ready                              # Tasks ready to work on
st update <id> --status running       # Claim task
st close <id> --reason "Done"         # Complete task

# Create
st create "Title" -t task -p 2 -d "Description"
st bug "Fix: X" -p 2                  # Shorthand for -t bug

# Subtasks & Steps
st subtask list <task-id>             # List subtasks
st step pass <task-id> <subtask-id> <step-number>  # Mark step passed
st subtask pass <task-id> <subtask-id>             # Mark subtask passed
```

### member-dis (Memory)

```bash
member-dis search "query"             # Search observations
member-dis expand <id>                # Get full content
member-dis index                      # Show context overview
```

---

## Additional Resources

- **Model Constants:** See `~/.claude/rules/model-standards.md` (never hardcode model strings)
- **Pre-Implementation Checks:** See `~/.claude/skills/pre-implementation-check/SKILL.md`
- **Issue Tracking:** Use `st create "Fix: X" -t bug` for discovered bugs
- **Memory System:** Context is auto-injected at session start via hooks

---

**Version**: 3.0.0
