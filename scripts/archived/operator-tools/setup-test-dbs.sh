#!/bin/bash
set -e

case "${1:-}" in
    --help|-h|help)
        cat <<'EOF'
Usage: st setup test-dbs [--dry-run] [--confirm TOKEN]

Create or refresh configured test databases. Run through st so
preview/confirmation stays consistent.
EOF
        exit 0
        ;;
esac

echo "=== Creating test databases ==="

COMPOSE_PROJECT="summitflow-stack"
USE_DOCKER=false

if [ -S /var/run/docker.sock ] && docker compose -p "$COMPOSE_PROJECT" ps --status running -q 2>/dev/null | grep -q .; then
    USE_DOCKER=true
fi

_run_psql() {
    if [ "$USE_DOCKER" = true ]; then
        docker compose -p "$COMPOSE_PROJECT" exec -T postgres psql -U admin "$@"
    else
        sudo -u postgres psql "$@"
    fi
}

_run_createdb() {
    if [ "$USE_DOCKER" = true ]; then
        docker compose -p "$COMPOSE_PROJECT" exec -T postgres createdb -U admin "$@"
    else
        sudo -u postgres createdb "$@"
    fi
}

# SummitFlow
echo "Creating summitflow_test..."
_run_createdb summitflow_test 2>/dev/null || echo "  Already exists"
_run_psql -c "GRANT ALL PRIVILEGES ON DATABASE summitflow_test TO summitflow_app;"
_run_psql -d summitflow_test -c "GRANT ALL ON SCHEMA public TO summitflow_app;"
_run_psql -d summitflow_test -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO summitflow_app;"

# Agent Hub
echo "Creating agent_hub_test..."
_run_createdb agent_hub_test 2>/dev/null || echo "  Already exists"
_run_psql -c "GRANT ALL PRIVILEGES ON DATABASE agent_hub_test TO agent_hub_app;"
_run_psql -d agent_hub_test -c "GRANT ALL ON SCHEMA public TO agent_hub_app;"
_run_psql -d agent_hub_test -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO agent_hub_app;"

# Portfolio AI
echo "Creating portfolio_ai_test..."
_run_createdb portfolio_ai_test 2>/dev/null || echo "  Already exists"
_run_psql -c "GRANT ALL PRIVILEGES ON DATABASE portfolio_ai_test TO portfolio_app;"
_run_psql -d portfolio_ai_test -c "GRANT ALL ON SCHEMA public TO portfolio_app;"
_run_psql -d portfolio_ai_test -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO portfolio_app;"

# Add TEST_DATABASE_URL to ~/.env.local if not present
echo ""
echo "=== Updating ~/.env.local ==="

# Read passwords from env or existing .env.local
SF_TEST_PASS="${SF_DB_PASSWORD:-}"
AH_TEST_PASS="${AH_DB_PASSWORD:-}"
PA_TEST_PASS="${PA_DB_PASSWORD:-}"

# Fall back to reading from .env.local
if [ -z "$SF_TEST_PASS" ] && [ -f ~/.env.local ]; then
    SF_TEST_PASS=$(grep "^SF_DB_PASSWORD=" ~/.env.local 2>/dev/null | cut -d'=' -f2- || true)
fi
if [ -z "$AH_TEST_PASS" ] && [ -f ~/.env.local ]; then
    AH_TEST_PASS=$(grep "^AH_DB_PASSWORD=" ~/.env.local 2>/dev/null | cut -d'=' -f2- || true)
fi
if [ -z "$PA_TEST_PASS" ] && [ -f ~/.env.local ]; then
    PA_TEST_PASS=$(grep "^PA_DB_PASSWORD=" ~/.env.local 2>/dev/null | cut -d'=' -f2- || true)
fi

# Determine postgres host
PG_HOST="localhost"
if [ "$USE_DOCKER" = true ]; then
    PG_HOST="localhost"  # Docker exposes 5432 to host
fi

if ! grep -q "TEST_DATABASE_URL" ~/.env.local 2>/dev/null; then
    echo "" >> ~/.env.local
    echo "# Test databases (pytest uses these instead of production)" >> ~/.env.local
    echo "TEST_DATABASE_URL=postgresql://summitflow_app:${SF_TEST_PASS}@${PG_HOST}:5432/summitflow_test" >> ~/.env.local
    echo "Added TEST_DATABASE_URL"
else
    echo "TEST_DATABASE_URL already in ~/.env.local"
fi

if ! grep -q "TEST_AGENT_HUB_DB_URL" ~/.env.local 2>/dev/null; then
    echo "TEST_AGENT_HUB_DB_URL=postgresql://agent_hub_app:${AH_TEST_PASS}@${PG_HOST}:5432/agent_hub_test" >> ~/.env.local
    echo "Added TEST_AGENT_HUB_DB_URL"
else
    echo "TEST_AGENT_HUB_DB_URL already in ~/.env.local"
fi

if ! grep -q "TEST_PORTFOLIO_DB_URL" ~/.env.local 2>/dev/null; then
    echo "TEST_PORTFOLIO_DB_URL=postgresql://portfolio_app:${PA_TEST_PASS}@${PG_HOST}:5432/portfolio_ai_test" >> ~/.env.local
    echo "Added TEST_PORTFOLIO_DB_URL"
else
    echo "TEST_PORTFOLIO_DB_URL already in ~/.env.local"
fi

echo ""
echo "=== Done ==="
echo "Test databases ready. Run: st check pytest -- tests/"
