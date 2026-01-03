# AGENTS.md

Core workflow for SummitFlow agents.

**Full docs via**: `POST /context/expand` with `doc:AGENTS.md`

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| Claim | `st update <id> --status running` |
| Complete | `st close <id> --reason "Done"` |
| Create bug | `st create "Fix: X" -t bug -p 2 -l "complexity:small,domains:backend"` |

---

## Landing the Plane (MANDATORY)

**Before ending session:**
1. `ruff check app/ --fix && mypy app/ && pytest tests/ -x`
2. `git add -A && git commit -m "feat: <msg>"`
3. `st close <id> --reason "Done"`
4. `git pull --rebase && git push`
5. `git status` = clean

**Never end with uncommitted/unpushed work.**

---

## Rules

- Track discovered bugs immediately → `st create` + `st dep add`
- Delete dead code (git has history)
- Ask for help vs workarounds
