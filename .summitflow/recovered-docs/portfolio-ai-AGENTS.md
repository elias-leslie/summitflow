# Portfolio-AI Agent Instructions

## Task Tracking (SummitFlow Tasks)

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

### Creating Tasks (Labels REQUIRED)
```bash
st create "Title" -t task|bug|chore -p 0-4 \
  -l "complexity:small,domains:backend" \
  -d "Description"

st dep add <child> <parent> --type discovered-from  # Link dependencies
```

**See `~/.claude/docs/task-reference.md` for full reference.**

### Complexity Labels (REQUIRED for /next_it efficiency)
| Label | Criteria | Agent Strategy |
|-------|----------|----------------|
| `complexity:small` | <3 files, <50 lines | Orchestrator direct |
| `complexity:medium` | 3-10 files, <200 lines | Light agent assist |
| `complexity:large` | >10 files OR multi-domain | Full specialist agents |

### Domain Labels (REQUIRED)
| Label | When |
|-------|------|
| `domains:backend` | Python/FastAPI changes |
| `domains:frontend` | React/Next.js changes |
| `domains:database` | Schema/migration changes |

### Priority Levels
| Level | Meaning |
|-------|---------|
| 0 | Critical (security, data loss) |
| 1 | High (major features, important bugs) |
| 2 | Medium (enhancements, minor bugs) |
| 3 | Low (polish, optimization) |
| 4 | Backlog (future ideas) |

---

## Feature Verification (Portfolio-AI)

For major features requiring evidence, use the verification system:

### Run Verification
```bash
curl -X POST localhost:8000/api/capabilities/features/FEAT-XXX/verify
```

### Capture Evidence
```bash
curl -X POST localhost:8000/api/artifacts/refresh \
  -H "Content-Type: application/json" \
  -d '{"feature_id": "FEAT-XXX", "criterion_id": "ac-001", "url": "http://192.168.8.233:3000/page"}'
```

### Link Task to Feature
```bash
st update <id> -d "Feature: FEAT-XXX"
```

### Verification Commands (Keep Using)
| Command | Purpose |
|---------|---------|
| `/verify_it FEAT-XXX` | Full-stack verification with evidence |
| `/test_it` | UI regression testing |

---

## Code Quality

### Testing Separation
| Layer | Purpose | Tool |
|-------|---------|------|
| Unit tests | Logic correctness | pytest |
| Type safety | Catch type errors | mypy |
| Lint/format | Code style | ruff, pre-commit |
| E2E verification | Feature works for users | Acceptance criteria |

### Rules
- Never skip pre-commit hooks
- pytest for business logic (edge cases, calculations)
- Acceptance criteria for integration/E2E
- Don't duplicate - if pytest tests it, acceptance criteria shouldn't

### Architecture Coherence
- **Before ANY new code**: Check for existing implementations (see `.claude/rules/architecture-coherence.md`)
- Run `/audit_it` for comprehensive codebase health audit
- Consolidate over create - extend existing utilities, don't duplicate

---

## Domain Rules

### Data
- Use `symbol` everywhere, NEVER `ticker`
- Verify before DELETE (SELECT first)
- No hardcoded limits on queries (`?limit=N`)

### UI/Backend
- Backend changes MUST have UI visibility
- Screenshots use `192.168.8.233:3000` (not localhost)

### Services
- Celery tasks for data fetching (no manual scripts)
- Use systemd scripts exclusively:
  ```bash
  bash ~/portfolio-ai/scripts/restart.sh  # After code changes
  bash ~/portfolio-ai/scripts/status.sh   # Check health
  ```

### Logs
```bash
journalctl --user -u portfolio-backend -f
journalctl --user -u portfolio-celery -f
```

---

## MANDATORY: Track Discovered Issues

**When you encounter ANY pre-existing bug, error, or issue during your work, you MUST:**

1. **Review ALL open Tasks** (do NOT filter by keywords - you might miss matches):
   ```bash
   st list --status pending --json | jq -r '.tasks[] | "\(.id) \(.title)"'
   ```
2. **If no task exists, CREATE + LINK IMMEDIATELY**:
   ```bash
   # Create the bug with complexity and domain labels
   st create "Fix: <clear description>" -t bug -p 2 \
     -l "complexity:small,domains:backend" \
     -d "Error: <exact error message>

   Location: <file:line>

   Found during: <parent-task-id> <task name>"

   # MANDATORY: Link with discovered-from dependency
   st dep add <new-id> <parent-task-id> --type discovered-from
   ```
3. **If task exists, UPDATE with new info**: `st update <id> -d "Additional context..."`

**This is MANDATORY. Do NOT:**
- Mention bugs in summaries without creating tasks
- Say "pre-existing issue, not related to this task" and move on
- Leave issues undocumented for future discovery
- Filter tasks by keywords (scan the FULL list)

**Every discovered issue = immediate task creation + dependency link. No exceptions.**

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| `?limit=200` on feature queries | No limit (get all) |
| Assume API field names | Verify with `curl ... \| jq keys` |
| DELETE without dry-run | SELECT/COUNT first |
| `localhost:3000` for screenshots | `192.168.8.233:3000` |
| Manual `systemctl` | Use scripts |
| `git stash` with uncommitted changes | Commit first |
| Start work with dirty working tree | Commit previous changes FIRST |
| Hardcode version numbers | Reference STACK.md |
| Skip pre-commit (`--no-verify`) | Fix the issues |
| Note bugs without creating tasks | Create task IMMEDIATELY |

---

## Session Protocol

### Start - MANDATORY

**Before starting ANY new work, verify clean working tree:**

#### 1. Check for Uncommitted Changes (MANDATORY)
```bash
git status --short
```
- If output shows files: **STOP** - you have uncommitted changes from a previous session
- **You MUST commit these BEFORE proceeding:**
  ```bash
  git diff --stat                    # Review what changed
  git add -A && git commit -m "WIP: Previous session changes"
  git push
  ```

#### 2. Find and Claim Work
```bash
st ready                              # Find work
st update <id> --status running       # Claim it
```

**Critical:** Uncommitted changes break multi-agent coordination. Never start new work on a dirty tree.

### End ("Landing the Plane") - MANDATORY

**All steps must complete before session ends. The plane hasn't landed until `git push` succeeds.**

#### 1. Run Quality Gates (if code changed)
```bash
cd backend && .venv/bin/ruff check app/ --fix
cd backend && .venv/bin/mypy app/ --no-error-summary
cd backend && .venv/bin/pytest tests/ -x --tb=short -q
```
- If builds/tests broken, file P0 issue before continuing

#### 2. Commit Your Implementation Changes
```bash
git add <your-changed-files>
git commit -m "feat/fix/chore: <title>

<WHY this change was needed - 1-2 sentences>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```
**IMPORTANT:** Commit message must be 100+ chars with reasoning (pre-commit hook enforces this).

#### 3. Update Task State
```bash
# Close completed tasks
st close <id> --reason "Completed: <summary>"

# Update in-progress work
st update <id> -d "Progress: <what was done>"

# Create tasks for discovered bugs (see MANDATORY section above)
```

#### 4. Push to Remote (NON-NEGOTIABLE)
```bash
git pull --rebase && git push
git status  # MUST show "up to date with origin/main"
```
- If pull/push fails, resolve and retry until successful
- Never say "ready to push when you are"—YOU must push
- Unpushed work breaks multi-agent coordination

#### 5. Verify Clean State
```bash
git status  # Should show: "nothing to commit, working tree clean"
```

#### 6. Choose Next Work
- Run `st ready` to identify next task
- Provide context for next session if needed

**Critical Rules:**
- Commit implementation BEFORE closing tasks (order matters!)
- Never stop before pushing—that leaves work stranded locally
- Lost issues = lost work = unacceptable

---

## Documentation

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](docs/core/ARCHITECTURE.md) | System design |
| [DEVELOPMENT.md](docs/core/DEVELOPMENT.md) | Workflows |
| [API_REFERENCE.md](docs/core/API_REFERENCE.md) | Endpoints |
| [STACK.md](docs/core/STACK.md) | Version numbers |

---

## Quick Reference

| Task | Command |
|------|---------|
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete work | `st close <id> --reason "Done"` |
| Verify feature | `/verify_it FEAT-XXX` |
| Restart services | `bash ~/portfolio-ai/scripts/restart.sh` |
| Check health | `bash ~/portfolio-ai/scripts/status.sh` |
| Run tests | `cd backend && pytest tests/ -v` |
| Check types | `cd backend && mypy app/` |
