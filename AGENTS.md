# SummitFlow Agent Instructions

Before anything else: run `bd onboard` and follow instructions.

## Task Tracking (Beads)

### Finding Work
```bash
bd ready --json              # Find unblocked work
bd list --status open --json # All open issues
bd stale --days 7 --json     # Forgotten issues
```

### Working on Issues
```bash
bd update <id> --status in_progress --json   # Claim work
bd close <id> --reason "Completed" --json    # Mark done
bd sync                                       # MANDATORY at session end
```

### Creating Issues (ENFORCED by pre-push hook)
```bash
# Labels are REQUIRED - pre-push hook blocks if missing!
bd create "Title" -t feature|bug|task -p 0-4 -d "Description" \
  --set-labels "complexity:small" --set-labels "domains:backend" --json

bd dep add <child> <parent>                  # Link dependencies
bd create "Found bug" --deps discovered-from:<parent-id> \
  --set-labels "complexity:small" --set-labels "domains:backend" --json
```

**See `.claude/rules/bead-quality.md` for full requirements.**

### Complexity Labels (REQUIRED)
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

## Code Quality

### Testing
| Layer | Purpose | Tool |
|-------|---------|------|
| Unit tests | Logic correctness | pytest |
| Type safety | Catch type errors | mypy |
| Lint/format | Code style | ruff, pre-commit |

### Rules
- Never skip pre-commit hooks
- pytest for business logic (edge cases, calculations)
- Don't duplicate - if pytest tests it, don't duplicate elsewhere

### Architecture Coherence
- **Before ANY new code**: Check for existing implementations (see `.claude/rules/architecture-coherence.md`)
- Consolidate over create - extend existing utilities, don't duplicate

---

## MANDATORY: Track Discovered Issues

**When you encounter ANY pre-existing bug, error, or issue during your work, you MUST:**

1. **Review ALL open Beads** (do NOT filter by keywords - you might miss matches):
   ```bash
   bd list --status open --json | jq -r '.[] | "\(.id) \(.title)"'
   ```
2. **If no bead exists, CREATE + LINK IMMEDIATELY**:
   ```bash
   # Create the bug with complexity and domain labels
   bd create --title "Fix: <clear description>" \
     --description "Error: <exact error message>

   Location: <file:line>

   Found during: <parent-bead-id> <task name>" \
     --priority 2 --type bug \
     --set-labels "complexity:small" --set-labels "domains:backend" \
     --json

   # MANDATORY: Link with discovered-from dependency
   bd dep add <new-id> <parent-bead-id> --type discovered-from
   ```
3. **If bead exists, UPDATE with new info**: `bd update <id> --notes "Additional context..."`

**This is MANDATORY. Do NOT:**
- Mention bugs in summaries without creating beads
- Say "pre-existing issue, not related to this task" and move on
- Leave issues undocumented for future discovery
- Filter beads by keywords (scan the FULL list)

**Every discovered issue = immediate bead creation + dependency link. No exceptions.**

---

## Services

```bash
bash ~/summitflow/scripts/restart.sh  # After code changes
bash ~/summitflow/scripts/status.sh   # Check health
```

### Logs
```bash
journalctl --user -u summitflow-backend -f
journalctl --user -u summitflow-frontend -f
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| `localhost:3001` for screenshots | `192.168.8.233:3001` (network IP) |
| Manual `systemctl` | Use scripts |
| `git stash` with uncommitted changes | Commit first |
| Start work with dirty working tree | Commit previous changes FIRST |
| Skip pre-commit (`--no-verify`) | Fix the issues |
| Note bugs without creating beads | Create bead IMMEDIATELY |

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
bd ready --json                              # Find work
bd update <id> --status in_progress --json   # Claim it
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

#### 2. Commit Your Implementation Changes FIRST
```bash
git add <your-changed-files>
git commit -m "feat/fix/chore: <title>

<WHY this change was needed - 1-2 sentences>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

#### 3. Update Beads State (AFTER implementation commit)
```bash
# Close completed issues
bd close <id> --reason "Completed: <summary>"

# Update in-progress work
bd update <id> --notes "Progress: <what was done>"

# Create beads for discovered bugs (see MANDATORY section above)
```

#### 4. Commit Beads Changes Separately
`bd close` and `bd update` modify `.beads/issues.jsonl`. Commit this BEFORE pulling:
```bash
git add .beads/issues.jsonl
git commit -m "chore: Update beads state after <task-id>

Closes/updates beads for: <brief description of what was completed>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

#### 5. Push to Remote (NON-NEGOTIABLE)
```bash
git pull --rebase && git push
git status  # MUST show "up to date with origin/main"
```
- If pull/push fails, resolve and retry until successful
- Never say "ready to push when you are"—YOU must push
- Unpushed work breaks multi-agent coordination

#### 6. Verify Clean State
```bash
git status  # Should show: "nothing to commit, working tree clean"
```

#### 7. Choose Next Work
- Run `bd ready --json` to identify next task
- Provide context for next session if needed

**Critical Rules:**
- Commit implementation BEFORE closing beads (order matters!)
- Commit beads changes BEFORE `git pull --rebase` (avoids unstaged changes error)
- Never stop before pushing—that leaves work stranded locally
- Lost issues = lost work = unacceptable

---

## Quick Reference

| Task | Command |
|------|---------|
| Find work | `st ready` |
| Start work | `st update <id> --status running` |
| Complete work | `st close <id> --reason "Done"` |
| Force close | `st close <id> --force` (bypass criteria) |
| List features | `st feature list` |
| Start feature | `st feature start FEAT-001` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Check health | `bash ~/summitflow/scripts/status.sh` |
| Run tests | `cd backend && pytest tests/ -v` |
| Check types | `cd backend && mypy app/` |

---

## SummitFlow Tasks (st CLI)

The `st` CLI is the primary task management interface for SummitFlow projects.

### Task Types
| Type | Purpose |
|------|---------|
| `feature` | Feature implementation (validates criteria on close) |
| `bug` | Bug fix |
| `task` | General task |

### Pre-Work Validation
Before starting a task, validate readiness:
```bash
curl -X POST localhost:8001/api/projects/summitflow/tasks/<task-id>/validate-ready
```

Checks:
- Task not already running/completed
- No incomplete blocking dependencies
- Feature-type tasks have linked feature with ≥1 criterion

### Close Validation (Criteria Enforcement)
For feature-type tasks linked to a feature, closing requires all acceptance criteria to pass:
```bash
st close <id> --reason "Done"    # Fails if criteria unsatisfied
st close <id> --force            # Bypass validation
```

### Feature Workflow
```bash
st feature list                  # List all features
st feature show FEAT-001         # Show feature with criteria
st feature start FEAT-001 -p 1   # Create task linked to feature
```
