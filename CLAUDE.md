# CLAUDE.md

SummitFlow - AI-assisted development. Read [AGENTS.md](AGENTS.md) for workflow.

**Full docs via**: `POST /context/expand` with `doc:CLAUDE.md` or `doc:AGENTS.md`

---

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `st ready` |
| Claim work | `st update <id> --status running` |
| Complete | `st close <id> --reason "Done"` |
| Verify capability | `st capability verify <id>` |
| Start services | `bash ~/summitflow/scripts/start.sh` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Run tests | `cd backend && .venv/bin/pytest` |
| Type check | `cd backend && .venv/bin/mypy app/` |

**Session End:** Commit → `st close` → `git pull --rebase && git push`

---

## URLs

| Service | URL |
|---------|-----|
| Production | https://dev.summitflow.dev |
| Local Frontend | http://localhost:3001 |
| Local Backend | http://localhost:8001 |
| API Docs | http://localhost:8001/docs |

---

## Rules

Mandatory rules in `.claude/rules/`: `issue-tracking.md`, `architecture-coherence.md`, `code-cleanliness.md`, `model-standards.md`

**Discovered bugs**: Create task with `st create "Fix: <desc>" -t bug -p 2 -l "complexity:small,domains:backend"`

---

## Services

`systemctl --user status|restart summitflow-backend`
`journalctl --user -u summitflow-backend -f`

---

**Version**: 2.5.0
