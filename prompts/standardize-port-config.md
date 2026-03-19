## Standardize Port Configuration Across All Projects

### Context

Each project (SummitFlow, Agent Hub, Terminal, Portfolio AI) hardcodes port numbers as fallback defaults in multiple files. The pattern `os.getenv("VAR", "http://localhost:8001")` is correct, but the same default port appears in 5-10 places per project instead of one.

### The Standard

Each project should define its own port defaults **once**, in its config module. Every other file in that project references the config — never a raw port number. Cross-project references use env vars with the config default as fallback.

### Port Allocation

| Service | Backend | Frontend |
|---------|---------|----------|
| Portfolio AI | 8000 | 3000 |
| SummitFlow | 8001 | 3001 |
| Terminal | 8002 | 3002 |
| Agent Hub | 8003 | 3003 |
| Monkey Fight | 4001 | — |

### What to do per project

**Backend** — Each project's `config.py` (or equivalent) should be the single source for:
- Its own backend/frontend port
- Any other project URLs it needs (e.g. Agent Hub URL)
- CORS origins

All other backend files that reference ports should import from config. No raw `"http://localhost:8001"` strings outside config.

**Frontend** — Each project's `next.config.ts` or `api-config.ts` should be the single place that defines fallback URLs. Proxy routes and other files reference that config.

**Docker Compose** — `~/summitflow/docker/compose/docker-compose.yml` already uses env vars for some ports. Ensure all port references use `${VAR:-default}` syntax reading from the `.env` file rather than hardcoded numbers.

### Files to fix per project

**SummitFlow** (`~/summitflow/`):
- `backend/app/config.py` — already has some, make it the canonical source for CORS origins, API base, Agent Hub URL
- `backend/app/api/docker/constants.py` — probe URLs and port lists should derive from config
- `backend/app/services/_agent_hub_config.py` — should import Agent Hub URL from config
- `backend/app/services/smoke_test.py` — health URLs should derive from config
- `frontend/next.config.ts` — single place for API URL defaults
- `frontend/lib/agent-hub-proxy.ts` — should reference next.config or api-config, not hardcode
- `frontend/app/proxy-hub/agent-hub/[...path]/route.ts` — same
- `scripts/tmux-agent-session-sync.py`, `scripts/codex-session-sync.py` — use env vars, fine as-is

**Agent Hub** (`~/agent-hub/`):
- `backend/app/config.py` — make port 8003 and CORS origins the single source
- `backend/mcp_server.py` — should reference config
- `frontend/next.config.ts` — single place for 8003 and 8001 URL defaults

**Terminal** (`~/terminal/`):
- `terminal/config.py` — already has port 8002, make it the single source for CORS and SummitFlow API URL
- `frontend/lib/hooks/use-terminal-orchestration.ts` — hardcodes `:8003` for Agent Hub, should use env/config
- `frontend/next.config.ts` — single place for API URL default

**Portfolio AI** (`~/portfolio-ai/`):
- `backend/app/config/__init__.py` — already has URLs, make it the single source
- `backend/app/config/cors.py` — should reference main config, not re-hardcode
- `frontend/next.config.ts` — single place for API URL default

### Rules
- Each project must remain fully independent — no cross-project Python/TS imports
- Env vars override defaults — `os.getenv("AGENT_HUB_URL", config.agent_hub_url)` is fine
- Don't create abstractions — just replace raw strings with references to the one config
- Don't touch test files — they can keep hardcoded values for test isolation
- Run `dt --check` per project before each commit (or `dt -P <project> --check`)
- Commit per project, not across projects
- Use `/commit_it --all` at the end to push everything

### Verification
After all changes, this should return zero hits in non-test production code:
```bash
for proj in summitflow agent-hub terminal portfolio-ai; do
  echo "=== $proj ==="
  grep -rn --include="*.py" --include="*.ts" --include="*.tsx" \
    -E "localhost:(8000|8001|8002|8003|3000|3001|3002|3003|4001)" \
    ~/$proj/backend/app/ ~/$proj/frontend/lib/ ~/$proj/frontend/next.config.ts 2>/dev/null \
    | grep -v "test" | grep -v "config\." | grep -v "Config"
done
```
