# CLAUDE.md

SummitFlow - AI-assisted development platform.

## Workflow

```
/plan_it → st import → /do_it → /commit_it
```

| Action | How |
|--------|-----|
| Find work | `st --compact ready` |
| Execute | `/do_it <task-id>` |
| Commit | `/commit_it` (NEVER direct git) |
| Restart | `bash ~/summitflow/scripts/restart.sh` |

**For st command syntax**: See `.claude/rules/st-cli.md` or run `st --help`.

## Invariants

1. **NEVER direct git commit** - `/commit_it` runs quality gates
2. **NEVER say "done"** without restart + verify
3. **Backend changes need UI** - complete the vertical slice
4. **Track bugs immediately** - `st bug "Fix: X"`

## URLs

| Local | Production |
|-------|------------|
| http://localhost:3001 | https://dev.summitflow.dev |
| http://localhost:8001/docs | (requires CF auth) |

---

**Version**: 5.0.0
