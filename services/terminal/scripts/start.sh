#!/bin/bash
# Start Terminal services via systemd (User Mode)

set -e

echo "================================"
echo "Starting Terminal Service"
echo "================================"
echo ""

echo "Starting terminal backend..."
systemctl --user start summitflow-terminal.service

echo "Starting terminal frontend..."
systemctl --user start summitflow-terminal-frontend.service

echo "Waiting for services..."
sleep 3

echo ""
echo "Service Status:"
echo "  Backend:  $(systemctl --user is-active summitflow-terminal.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo "  Frontend: $(systemctl --user is-active summitflow-terminal-frontend.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo ""
echo "URLs:"
echo "  Local: http://localhost:3002"
echo "  Prod:  https://terminal.summitflow.dev"
echo ""
