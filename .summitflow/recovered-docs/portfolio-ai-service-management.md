# Service Management

Systemd-based service control - NEVER manually start/stop processes.

## CRITICAL: Use Scripts Exclusively

**NEVER manually start/stop processes. Use scripts exclusively.**

### Service Control Scripts

```bash
bash ~/portfolio-ai/scripts/start.sh    # Start all
bash ~/portfolio-ai/scripts/restart.sh  # Restart all  ← RUN AFTER CODE CHANGES
bash ~/portfolio-ai/scripts/shutdown.sh # Stop all
bash ~/portfolio-ai/scripts/status.sh   # Check status
```

### Services

| Service | Purpose |
|---------|---------|
| `portfolio-backend` | FastAPI backend |
| `portfolio-celery` | Celery worker |
| `portfolio-beat` | Celery beat scheduler |
| `portfolio-frontend` | Next.js frontend |

### Logs (User-Mode Services)

```bash
# CORRECT: User-mode journalctl (ONLY valid log location)
journalctl --user -u portfolio-celery -f
journalctl --user -u portfolio-backend -f
journalctl --user -u portfolio-celery-beat -f
journalctl --user -u portfolio-frontend -f

# Recent logs (last 100 lines)
journalctl --user -u portfolio-celery -n 100

# Logs since specific time
journalctl --user -u portfolio-backend --since "1 hour ago"
```

**WRONG paths (do NOT exist):**
```bash
# These paths do NOT exist - don't use them
tail -f /var/log/portfolio-ai/celery-error.log  # WRONG
tail -f /var/log/portfolio-ai/backend-error.log  # WRONG
```

### IMPORTANT: User-Mode Services

Services run via `systemctl --user`, NOT system-wide `systemctl`.

```bash
# WRONG - will say "service not found"
sudo systemctl status portfolio-celery

# CORRECT - user-mode check
systemctl --user status portfolio-celery

# BEST - use the status script
bash ~/portfolio-ai/scripts/status.sh
```

### After Code Changes

ALWAYS run `bash ~/portfolio-ai/scripts/restart.sh` after:
- Backend code changes (to reload uvicorn)
- Celery task changes (to reload worker)
- Any scheduled task changes (to reload beat)
