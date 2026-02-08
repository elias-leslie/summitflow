#!/bin/bash
set -euo pipefail

# Phase 1: Install Docker (requires sudo)
if ! command -v docker &>/dev/null; then
    echo "=== Installing Docker CE ==="
    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
    sudo systemctl enable docker
    sudo systemctl start docker
else
    echo "=== Docker already installed ==="
fi

# Ensure user is in docker group
if ! groups | grep -q docker; then
    echo "=== Adding user to docker group ==="
    sudo usermod -aG docker "$(whoami)"
    echo ""
    echo "You were added to the docker group."
    echo "Run: newgrp docker && $0 --post-group"
    echo "(This activates the group and re-runs the script)"
    exit 0
fi

# Phase 2: Pull and start Hatchet (no sudo needed)
echo "=== Pulling Hatchet Lite image ==="
docker pull ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest

# Stop existing container if running
docker stop hatchet-engine 2>/dev/null || true

echo "=== Starting Hatchet engine ==="
docker run -d --rm --name hatchet-engine \
    --network host \
    -e DATABASE_URL="${HATCHET_DATABASE_URL:-postgresql://db_admin:u0T1C3Y67pKtqKNd2wvvGOMb@localhost:5432/hatchet?sslmode=disable}" \
    -e SERVER_AUTH_COOKIE_INSECURE=true \
    -e SERVER_GRPC_BIND_ADDRESS=0.0.0.0 \
    -e SERVER_GRPC_PORT=7077 \
    -e SERVER_PORT=8888 \
    ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest

echo "=== Waiting for Hatchet engine (up to 60s) ==="
for i in $(seq 1 60); do
    if curl -sf http://localhost:8888/api/v1/meta > /dev/null 2>&1; then
        echo "Hatchet engine is up!"
        curl -s http://localhost:8888/api/v1/meta
        echo
        break
    fi
    printf "  waiting... (%d/60)\n" "$i"
    sleep 1
done

if ! curl -sf http://localhost:8888/api/v1/meta > /dev/null 2>&1; then
    echo "ERROR: Hatchet engine failed to start."
    echo "Check: docker logs hatchet-engine"
    exit 1
fi

echo ""
echo "================================================"
echo "  Hatchet UI: http://localhost:8888"
echo "  gRPC:       localhost:7077"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:8888 in your browser"
echo "  2. Create an account / log in"
echo "  3. Go to Settings > API Tokens > Generate"
echo "  4. Paste the token back to Claude"
echo ""
echo "Once confirmed working, stop this test container:"
echo "  docker stop hatchet-engine"
echo ""
echo "Then enable the systemd service:"
echo "  systemctl --user enable --now hatchet-engine"
