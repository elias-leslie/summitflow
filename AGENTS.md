# AGENTS.md

Core workflow for SummitFlow agents.

---

## Task Workflow

### Finding Work
```bash
st ready                              # Find unblocked work
st list --status pending              # All pending tasks
st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'
```

### Working on Tasks
```bash
st update <id> --status running       # Claim work
st close <id> --reason "Completed"    # Mark done
```

### Creating Tasks
```bash
st create "Title" -t task|bug|chore -p 0-4 \
  -l "complexity:small,domains:backend" \
  -d "Description"

st dep add <child> <parent> --type discovered-from
```

### Labels (REQUIRED)

**Complexity:**
| Label | Criteria |
|-------|----------|
| `complexity:small` | <3 files, <50 lines |
| `complexity:medium` | 3-10 files, <200 lines |
| `complexity:large` | >10 files OR multi-domain |

**Domains:**
| Label | When |
|-------|------|
| `domains:backend` | Python/FastAPI changes |
| `domains:frontend` | React/Next.js changes |
| `domains:database` | Schema/migration changes |

---

## Session Protocol

### Start - MANDATORY

**Before starting ANY new work, verify clean working tree:**

```bash
git status --short
```
- If output shows files: **STOP** - commit previous changes first
- Then find and claim work: `st ready && st update <id> --status running`

### End ("Landing the Plane") - MANDATORY

**All steps must complete before session ends.**

#### 1. Run Quality Gates
```bash
cd backend && .venv/bin/ruff check app/ --fix
cd backend && .venv/bin/mypy app/ --no-error-summary
cd backend && .venv/bin/pytest tests/ -x --tb=short -q
```

#### 2. Commit Implementation
```bash
git add <your-changed-files>
git commit -m "feat/fix/chore: <title>

<WHY this change was needed - 1-2 sentences>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

#### 3. Update Task State
```bash
st close <id> --reason "Completed: <summary>"
```

#### 4. Push to Remote (NON-NEGOTIABLE)
```bash
git pull --rebase && git push
git status  # MUST show "up to date with origin/main"
```

**Never end with uncommitted/unpushed work.**

---

## Discovered Issues - MANDATORY

When you encounter ANY pre-existing bug during work:

1. **REVIEW ALL OPEN TASKS** (scan full list):
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

## Code Quality

### Testing Separation
| Layer | Purpose | Tool |
|-------|---------|------|
| Unit tests | Logic correctness | pytest |
| Type safety | Catch type errors | mypy |
| Lint/format | Code style | ruff, pre-commit |

### Architecture Coherence
- **Before ANY new code**: Check for existing implementations
- Consolidate over create - extend existing utilities, don't duplicate
- Delete dead code (git has history)

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Start work with dirty tree | Commit previous changes FIRST |
| Skip pre-commit | Fix the issues |
| Note bugs without tasks | Create task IMMEDIATELY |
| Hardcode model strings | Use constants.py |
| `git stash` with uncommitted | Commit first |
| "I'll refactor later" | Create a task |

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| List pending | `st list --status pending` |
| View task | `st show <id>` |
| Claim work | `st update <id> --status running` |
| Complete | `st close <id> -r "Done"` |
| Create bug | `st bug "Fix: X" -p 2 -l "complexity:small,domains:backend"` |
| Link dependency | `st dep add <child> <parent> --type discovered-from` |
| Search memory | `member-dis search "query"` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Run tests | `cd backend && .venv/bin/pytest tests/ -v` |
| Check types | `cd backend && .venv/bin/mypy app/` |
| View logs | `journalctl --user -u summitflow-backend -f` |

**See CLAUDE.md for full command reference with all flags and options.**
