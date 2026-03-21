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

echo "Starting terminal backend..."
systemctl --user start summitflow-terminal.service

echo "Starting terminal frontend..."
systemctl --user start summitflow-terminal-frontend.service

echo ""
echo "Waiting for services to be ready..."
sleep 3

# Run status check
bash "$SCRIPT_DIR/status.sh"
