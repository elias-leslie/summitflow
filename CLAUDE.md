# CLAUDE.md

SummitFlow - AI-assisted development platform. See [AGENTS.md](AGENTS.md) for workflow.

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

## Model Constants

Use `backend/app/constants.py` - never hardcode model strings.

| Constant | Model |
|----------|-------|
| CLAUDE_SONNET | claude-sonnet-4-5 (default) |
| CLAUDE_OPUS | claude-opus-4-5 |
| GEMINI_FLASH | gemini-3-flash-preview |

Forbidden: `gemini-2.*`, `claude-3-*`, hardcoded strings.

---

## Cloudflare Access

Production URLs require auth headers. Credentials: `~/.cloudflare-access`

```bash
source ~/.cloudflare-access && curl -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" https://dev.summitflow.dev/api/health
```

---

## Core Rules

1. **Direct, technical, no fluff** - Sparring partner, not cheerleader
2. **Backend changes need UI visibility** - Complete the vertical slice
3. **Track discovered bugs immediately** - `st create "Fix: X" -t bug`
4. **SummitFlow vs App** - Dev tooling goes in SummitFlow. User-facing functionality stays in the app.
5. **Consolidate over create** - Check for existing implementations before writing new code

---

## Architecture Coherence

Before writing ANY new code, function, class, table, or column - verify it doesn't already exist.

### Pre-Implementation Checklist

1. **Search for existing implementations**
   ```bash
   grep -r "def similar_name" backend/
   grep -r "class SimilarName" backend/
   ```

2. **Check established patterns**
   - `backend/app/utils/` - existing utilities
   - `backend/app/services/` - existing service patterns
   - `frontend/lib/` and `frontend/utils/` - frontend helpers

3. **For DB changes: review existing schema**
   ```bash
   psql -d summitflow -c "\dt"
   psql -d summitflow -c "\d table_name"
   ```

### SummitFlow vs App Code

| Belongs in SummitFlow (dev tooling) | Stays in App (operational) |
|-------------------------------------|----------------------------|
| Features/capabilities tracking | The actual app functionality |
| Evidence capture & verification | User-facing dashboards |
| Task architecture explorer | Background jobs themselves |
| Code quality tools | Business logic |

**Test:** Would a user of the finished app need this? → App code
**Test:** Is this for understanding/developing the codebase? → SummitFlow

---

## Issue Tracking - MANDATORY

When you encounter ANY pre-existing bug during work:

1. **REVIEW ALL OPEN TASKS:**
   ```bash
   st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'
   ```

2. **CREATE if none exists:**
   ```bash
   st create "Fix: <description>" -t bug -p 2 \
     -l "complexity:small,domains:backend" \
     -d "Error: <exact error>

   Location: <file:line>

   Found during: <parent-task-id>"

   st dep add <new-id> <parent-task-id> --type discovered-from
   ```

**Every discovered issue = immediate task creation. No exceptions.**

---

## Memory System

The memory system is currently being aligned with claude-mem patterns. See `docs/memory-system-alignment.md` for the full reference.

**Quick access:**
- `member-dis search "query"` - Search observations
- `member-dis expand <id>` - Get full observation
- Context is auto-injected at session start

---

**Version**: 2.7.0
