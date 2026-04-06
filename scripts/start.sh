#!/bin/bash
# Start all SummitFlow services via systemd (User Mode)

set -e
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

echo "================================"
echo "Starting SummitFlow Platform"
echo "================================"
echo ""

echo "Starting backend..."
systemctl --user start summitflow-backend.service

echo "Starting frontend..."
systemctl --user start summitflow-frontend.service

echo "Starting A-Term backend..."
systemctl --user start a-term-backend.service

echo "Starting A-Term frontend..."
systemctl --user start a-term-frontend.service

echo ""
echo "Waiting for services to be ready..."
sleep 3

# Run status check
bash "$SCRIPT_DIR/status.sh"
