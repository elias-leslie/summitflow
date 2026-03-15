# SummitFlow Ecosystem — Docker Self-Hosting Guide

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/summitflow-solutions/summitflow/main/docker/install.sh | bash
```

The installer will:
1. Check Docker prerequisites
2. Ask which projects to install
3. Generate secure passwords
4. Pull images and start the stack

## Manual Setup

```bash
# Clone the compose files
mkdir ~/summitflow-docker && cd ~/summitflow-docker
cp /path/to/summitflow/docker/compose/* .

# Configure
cp .env.example .env
# Edit .env with your passwords and API keys

# Start (pick a profile)
docker compose --profile summitflow up -d     # SummitFlow only
docker compose --profile agent-hub up -d      # Agent Hub + infra
docker compose --profile full up -d           # Everything
```

## Profiles

| Profile | Services |
|---------|----------|
| `infra` | PostgreSQL, Redis, Hatchet |
| `summitflow` | SummitFlow API + Web + Worker + infra |
| `agent-hub` | Agent Hub API + Web + Worker + infra |
| `terminal` | Terminal API + Web + infra |
| `portfolio` | Portfolio AI API + Web + Worker + infra |
| `monkey-fight` | Monkey Fight + infra |
| `browser` | Agent Browser (Chrome for Testing) |
| `full` | All of the above |

## Service Ports

| Service | Port |
|---------|------|
| SummitFlow Web | 3001 |
| SummitFlow API | 8001 |
| Agent Hub Web | 3003 |
| Agent Hub API | 8003 |
| Terminal Web | 3002 |
| Terminal API | 8002 |
| Portfolio AI Web | 3000 |
| Portfolio AI API | 8000 |
| Monkey Fight | 4001 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| Hatchet | 7077, 8888 |

## Configuration

All configuration is via environment variables in `.env`. See `.env.example` for the full reference.

### Required Variables

- `POSTGRES_PASSWORD` — PostgreSQL superuser password
- `SF_DB_PASSWORD`, `AH_DB_PASSWORD`, `PA_DB_PASSWORD` — Per-project DB passwords

### Optional Variables

- `TAG` — Docker image tag (default: `latest`)
- `ANTHROPIC_API_KEY` — For Agent Hub AI features
- `OPENAI_API_KEY` — For Agent Hub AI features
- `HF_TOKEN` — For Portfolio AI ML model downloads

## Development Mode

For local development with hot reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile summitflow up
```

This bind-mounts source code and uses `--reload` for both Python and Next.js.

## Upgrade

```bash
docker compose pull
docker compose --profile <your-profile> up -d
```

Images are rebuilt on every tagged release. Data is persisted in Docker volumes.

## Backup & Restore

### Create Backup
```bash
# Via st CLI (if installed)
st docker backup --note "pre-upgrade"

# Via docker compose directly
docker compose exec -T postgres pg_dumpall -U admin > backup.sql
```

### Restore
```bash
# Via st CLI
st docker restore ~/docker-backups/docker-pgdump-20260314-120000.sql

# Via docker compose directly
cat backup.sql | docker compose exec -T postgres psql -U admin
```

## Terminal tmux Notes

The Terminal service runs tmux inside its container for self-contained terminal sessions. Limitations:

- Cannot attach to host-level tmux sessions (Claude Code, etc.)
- For full tmux integration on your dev machine, run Terminal natively (systemd)
- Advanced: mount host tmux socket with `--pid host` for host tmux access

## Troubleshooting

### Services won't start
```bash
docker compose --profile <profile> logs
docker compose ps --all
```

### Database connection errors
Check that postgres is healthy: `docker compose ps postgres`
Verify passwords match between `.env` and what `init-db.sh` created.

### Reset everything
```bash
docker compose --profile full down --volumes
docker compose --profile full up -d
```
This destroys all data and re-initializes databases.
