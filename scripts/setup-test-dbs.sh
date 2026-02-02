#!/bin/bash
set -e

echo "=== Creating test databases ==="

# SummitFlow
echo "Creating summitflow_test..."
sudo -u postgres createdb summitflow_test 2>/dev/null || echo "  Already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE summitflow_test TO summitflow_app;"
sudo -u postgres psql -d summitflow_test -c "GRANT ALL ON SCHEMA public TO summitflow_app;"
sudo -u postgres psql -d summitflow_test -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO summitflow_app;"

# Agent Hub
echo "Creating agent_hub_test..."
sudo -u postgres createdb agent_hub_test 2>/dev/null || echo "  Already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE agent_hub_test TO agent_hub_app;"
sudo -u postgres psql -d agent_hub_test -c "GRANT ALL ON SCHEMA public TO agent_hub_app;"
sudo -u postgres psql -d agent_hub_test -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO agent_hub_app;"

# Add TEST_DATABASE_URL to ~/.env.local if not present
echo ""
echo "=== Updating ~/.env.local ==="

if ! grep -q "TEST_DATABASE_URL" ~/.env.local 2>/dev/null; then
    echo "" >> ~/.env.local
    echo "# Test databases (pytest uses these instead of production)" >> ~/.env.local
    echo "TEST_DATABASE_URL=postgresql://summitflow_app:J1pev9kAYtySFkOeXn1bG1pY@localhost:5432/summitflow_test" >> ~/.env.local
    echo "Added TEST_DATABASE_URL"
else
    echo "TEST_DATABASE_URL already in ~/.env.local"
fi

if ! grep -q "TEST_AGENT_HUB_DB_URL" ~/.env.local 2>/dev/null; then
    echo "TEST_AGENT_HUB_DB_URL=postgresql://agent_hub_app:AgentHub2026SecurePass@localhost:5432/agent_hub_test" >> ~/.env.local
    echo "Added TEST_AGENT_HUB_DB_URL"
else
    echo "TEST_AGENT_HUB_DB_URL already in ~/.env.local"
fi

echo ""
echo "=== Done ==="
echo "Test databases ready. Run: dt pytest tests/"
