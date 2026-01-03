# AGENTS.md

Core workflow for SummitFlow agents.

---

## Labels (REQUIRED)

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

## Code Quality

### Testing Separation
| Layer | Purpose | Tool |
|-------|---------|------|
| Unit tests | Logic correctness | pytest |
| Type safety | Catch type errors | mypy |
| Lint/format | Code style | ruff, pre-commit |

### Architecture Coherence
- **Before ANY new code**: Use pre-implementation-check skill
- Consolidate over create - extend existing utilities, don't duplicate
- Delete dead code (git has history)

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Start work with dirty tree | Commit previous changes FIRST |
| Skip pre-commit | Fix the issues |
| Note bugs without tasks | Create task with `st bug` IMMEDIATELY |
| Hardcode model strings | Use constants.py |
| `git stash` with uncommitted | Commit first |
| "I'll refactor later" | Create a task with `/task_it` |
| Create without checking | Run pre-implementation-check first |
| Mark step complete without proof | Verify file exists with `ls`, run command to confirm |
| Drop columns without updating code | `grep -r <column> app/` must return empty |
| Add schema SQL without running | Run `init_schema()` and verify table exists |
| Backend-only removal tasks | Include frontend steps if UI uses the feature |
| Commit UI changes without testing | Screenshot page FIRST, check 0 console errors |

---

## Verification Gates (Post-Implementation)

**Before marking ANY step complete:**

| Step Type | Verification |
|-----------|--------------|
| "Create file X" | `ls -la <path>` shows file exists and non-empty |
| "Write tests for Y" | `pytest <test-file> --collect-only` shows tests |
| "Create table Z" | Query `information_schema.tables` shows table |
| "Remove column W" | `grep -r "W" app/` returns nothing in backend AND frontend |
| "Add function F" | `grep -n "def F" app/` shows location |
| "UI changes" | Screenshot affected page, verify 0 console errors |

**Before marking subtask complete:**
- All steps actually verified (not just marked)
- Tests pass: `pytest tests/ -x`
- Types pass: `mypy app/`

**Use `/task_verify <task-id>` to audit completed work.**

---

**See CLAUDE.md for essential commands. Use `/do_it` for task execution, `/task_it` for planning.**
