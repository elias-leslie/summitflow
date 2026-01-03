# CLAUDE.md

Portfolio AI Platform - AI-led investment intelligence system.

**Read [AGENTS.md](AGENTS.md) for task tracking and workflow.**
**Read [ARCHITECTURE.md](docs/core/ARCHITECTURE.md) for system design.**

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

## IMPORTANT: Stock/Trading Questions (Agent Hub)

**When users ask about stocks, portfolio, or trading from the Agent Hub:**

```bash
# ALWAYS call this FIRST - do NOT web search before checking our data
curl http://localhost:8000/api/symbols/{SYMBOL}/intelligence
```

This returns OUR analysis: scores, signals, technicals, fundamentals, news, portfolio position, and personalized recommendations. **Use this data to answer, not generic web results.**

---

## Quick Reference

| Action | Command |
|--------|---------|
| Auto work on next task | `/next_it` (or `/next_it --max`) |
| Fix audit issues first | `/next_it --audit` (or `--max --audit`) |
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete work | `st close <id> --reason "Done"` |
| **End session** | See "Landing the Plane" in AGENTS.md |
| Verify feature | `/verify_it FEAT-XXX` |
| Restart services | `bash ~/portfolio-ai/scripts/restart.sh` |
| Check health | `bash ~/portfolio-ai/scripts/status.sh` |
| Query files | `curl localhost:8000/api/files?path=backend&sort=lines_of_code` |
| Codebase health | `/audit_it` (--quick, --fix, --deep) |

**Session End (NON-NEGOTIABLE):** Commit impl → `st close` → `git pull --rebase && git push` (see AGENTS.md for full checklist)

---

## Domain Skills (Auto-Loaded)

| Skill | Use When |
|-------|----------|
| `python-patterns` | Python backend, FastAPI, Celery |
| `react-patterns` | React/Next.js components |
| `postgresql-patterns` | Database queries, migrations |
| `browser-automation` | Screenshots, UI testing |
| `code-quality` | Quality checks, security |

---

## Rules (5 files in `.claude/rules/`)

| Rule | Purpose |
|------|---------|
| `issue-tracking.md` | **MANDATORY: Track ALL discovered bugs** |
| `architecture-coherence.md` | **MANDATORY: Anti-silo, DRY, holistic architecture** |
| `ui-backend-lockstep.md` | Backend changes need UI visibility |
| `data-safety.md` | Symbol rules, destructive ops |
| `data-sources.md` | Celery patterns |
| `service-management.md` | Systemd ops |

---

## Commands (7 files in `.claude/commands/`)

| Command | Purpose |
|---------|---------|
| `/next_it` | Auto-select and work on next task |
| `/verify_it` | Full-stack verification with evidence |
| `/audit_it` | Codebase health audit (metrics, lint, security, cleanup) |
| `/test_it` | UI regression testing |
| `/review_files` | Code review for specific files |
| `/back_it` | Backup ops |
| `/update_it` | Stack versions |

---

## Documentation

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | Task tracking, workflow |
| [ARCHITECTURE.md](docs/core/ARCHITECTURE.md) | System design |
| [DEVELOPMENT.md](docs/core/DEVELOPMENT.md) | Dev workflows |
| [API_REFERENCE.md](docs/core/API_REFERENCE.md) | Endpoints |

---

**Version**: 3.4.0 | **Updated**: 2025-12-19
