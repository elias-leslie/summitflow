#!/bin/bash
# Start all SummitFlow services via systemd (User Mode)

set -e

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
bash ~/summitflow/scripts/status.sh
