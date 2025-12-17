# CLAUDE.md

SummitFlow - AI-assisted software development platform.

## Quick Reference

| Action | Command |
|--------|---------|
| Start services | `bash ~/summitflow/scripts/start.sh` |
| Restart services | `bash ~/summitflow/scripts/restart.sh` |
| Stop services | `bash ~/summitflow/scripts/shutdown.sh` |
| Check status | `bash ~/summitflow/scripts/status.sh` |
| Run tests | `cd ~/summitflow/backend && source .venv/bin/activate && pytest` |
| Create schema | `cd ~/summitflow/backend && source .venv/bin/activate && python -m app.storage.connection` |

## URLs

| Service | URL |
|---------|-----|
| HTTPS (nginx) | https://192.168.8.233:444 |
| Local Frontend | http://localhost:3001 |
| Local Backend | http://localhost:8001 |
| API Docs | http://localhost:8001/docs |

## Service Management

Services run via `systemctl --user` (user-mode systemd).

```bash
# Check specific service
systemctl --user status summitflow-backend
systemctl --user status summitflow-frontend

# View logs
journalctl --user -u summitflow-backend -f
journalctl --user -u summitflow-frontend -f

# Manual control
systemctl --user start summitflow-backend
systemctl --user stop summitflow-frontend
systemctl --user restart summitflow-backend
```

## Project Structure

```
summitflow/
├── backend/
│   ├── app/
│   │   ├── api/       # FastAPI routers
│   │   ├── services/  # Business logic
│   │   ├── storage/   # Database access
│   │   └── main.py    # FastAPI app
│   └── .venv/         # Python virtual environment
├── frontend/
│   ├── app/           # Next.js pages
│   ├── components/    # React components
│   └── lib/           # API client, utilities
└── scripts/
    ├── systemd/       # Service files
    ├── nginx/         # nginx config
    ├── restart.sh     # Restart all services
    ├── status.sh      # Check service status
    ├── start.sh       # Start all services
    └── shutdown.sh    # Stop all services
```

## Database

PostgreSQL database: `summitflow`

Core tables:
- `projects` - Registered target applications

Future tables (Phase 2+):
- `features` - Feature tracking per project
- `acceptance_criteria` - Feature verification criteria
- `artifacts` - Evidence (screenshots, logs)
- `sitemap_entries` - Discovered endpoints

## API Conventions

- All endpoints scoped by `project_id`
- Timestamps in UTC (ISO 8601)
- IDs are prefixed (e.g., `FEAT-001`, `AC-001`)

## First-Time Setup

```bash
# 1. Install and enable services (run once)
bash ~/summitflow/scripts/setup-services.sh

# 2. Start services
bash ~/summitflow/scripts/start.sh

# 3. Access at https://192.168.8.233:444
```

## Migration Plan

Extracted from portfolio-ai. See:
- Plan: `/home/kasadis/.claude/plans/sparkling-meandering-cascade.md`
- Epic: `portfolio-ai-43g`
- Phase 1: `portfolio-ai-2kp` (CLOSED)
- Phase 2: `portfolio-ai-6lg` (Sitemap extraction)
