# SummitFlow

Task management and orchestration platform for AI-assisted development.

**Project context injected via memory system at session start.**

See `~/.claude/CLAUDE.md` for memory API reference.

## Architecture

```
summitflow/
├── backend/           # Backend (FastAPI, port 8001)
│   ├── app/
│   │   ├── api/       # REST endpoints
│   │   ├── services/  # Business logic
│   │   ├── models/    # SQLAlchemy models
│   │   └── workflows/  # Background tasks (Hatchet workflows)
│   └── tests/
├── frontend/          # Frontend (Next.js, port 3001)
│   ├── app/           # Pages (App Router)
│   ├── components/    # React components
│   └── lib/           # Utilities, hooks, API clients
├── scripts/           # Shared scripts (canonical source, symlinked by other projects)
│   ├── rebuild.sh     # Build and restart services
│   ├── backup.sh      # Database backup to NAS
│   ├── dev-tools.sh   # Quality tool wrapper (dt CLI)
│   ├── commit.sh      # Multi-repo commit handler
│   └── lib/           # Shared script libraries
└── tasks/             # Task specifications and state
```

## Database

PostgreSQL. See `.index.yaml` for full table and endpoint lists.

## Shared Scripts

SummitFlow is the canonical source for shared scripts. Other projects symlink to these:
- `rebuild.sh`, `backup.sh`, `restore.sh`, `dev-tools.sh`, `lib/`
