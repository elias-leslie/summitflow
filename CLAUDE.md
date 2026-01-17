# CLAUDE.md

SummitFlow - AI-assisted development platform.

## Principle

Fight entropy. Leave the codebase better than you found it. Patterns you establish will be copied. Corners you cut will be cut again.

## Workflow

```
/plan_it → st import → /do_it → /commit_it
```

| Action | How |
|--------|-----|
| Find work | `st ready` |
| Execute | `/do_it <task-id>` |
| Quality check | `dt --check` or `st health` |
| Commit | `/commit_it` (NEVER direct git) |
| Restart | `bash ~/summitflow/scripts/restart.sh` |

## Invariants

1. **NEVER direct git commit** - `/commit_it` runs quality gates
2. **NEVER say "done"** without restart + verify
3. **Backend changes need UI** - complete the vertical slice
4. **Track bugs immediately** - `st bug "Fix: X"`
5. **Use `dt` for all quality checks** - `dt --check`, `dt ruff`, `dt pytest` (see `dev-tools-exclusive.md`)
6. **Check `st health`** - quality gate must pass before autonomous execution

## URLs

| Local | Production |
|-------|------------|
| http://localhost:3001 | https://dev.summitflow.dev |
| http://localhost:8001/docs | https://api.summitflow.dev (CF auth) |

---

**Version**: 5.2.0
