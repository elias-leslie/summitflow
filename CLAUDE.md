# CLAUDE.md

SummitFlow - AI-assisted development. See [AGENTS.md](AGENTS.md) for workflow.

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
4. **SummitFlow vs App**: Dev tooling → SummitFlow. User-facing → App.

---

**Version**: 2.6.0
