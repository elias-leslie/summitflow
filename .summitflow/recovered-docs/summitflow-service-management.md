# Service Management

Systemd-based service control - NEVER manually start/stop processes.

## CRITICAL: Use Scripts Exclusively

**NEVER manually start/stop processes. Use scripts exclusively.**

### Service Control Scripts

```bash
bash ~/summitflow/scripts/start.sh    # Start all
bash ~/summitflow/scripts/restart.sh  # Restart all  ← RUN AFTER CODE CHANGES
bash ~/summitflow/scripts/shutdown.sh # Stop all
bash ~/summitflow/scripts/status.sh   # Check status
```

### Services

| Service | Purpose |
|---------|---------|
| `summitflow-backend` | FastAPI backend |
| `summitflow-frontend` | Next.js frontend |

### Logs (User-Mode Services)

```bash
# CORRECT: User-mode journalctl (ONLY valid log location)
journalctl --user -u summitflow-backend -f
journalctl --user -u summitflow-frontend -f

# Recent logs (last 100 lines)
journalctl --user -u summitflow-backend -n 100

# Logs since specific time
journalctl --user -u summitflow-backend --since "1 hour ago"
```

### IMPORTANT: User-Mode Services

Services run via `systemctl --user`, NOT system-wide `systemctl`.

```bash
# WRONG - will say "service not found"
sudo systemctl status summitflow-backend

# CORRECT - user-mode check
systemctl --user status summitflow-backend

# BEST - use the status script
bash ~/summitflow/scripts/status.sh
```

### After Code Changes

ALWAYS run `bash ~/summitflow/scripts/restart.sh` after:
- Backend code changes (to reload uvicorn)
- Any configuration changes

**For frontend changes**, also rebuild:
```bash
cd ~/summitflow/frontend && npm run build
systemctl --user restart summitflow-frontend
```

### Verifying UI Changes (CRITICAL)

**ALWAYS verify UI changes from the production URL, NOT localhost.**

| URL | Purpose |
|-----|---------|
| https://dev.summitflow.dev | Production (via Cloudflare Tunnel) - USE THIS |
| http://localhost:3001 | Local only - DO NOT use for verification |

**Why?** Cloudflare Tunnel serves the production build. Localhost may show cached/stale content.

**Verification workflow:**
1. Make code changes
2. Rebuild frontend: `npm run build`
3. Restart: `bash ~/summitflow/scripts/restart.sh`
4. Verify at: https://dev.summitflow.dev
