#!/bin/bash
# Stop Terminal services via systemd (User Mode)

echo "================================"
echo "Stopping Terminal Service"
echo "================================"
echo ""

echo "Stopping terminal frontend..."
systemctl --user stop summitflow-terminal-frontend.service || true

echo "Stopping terminal backend..."
systemctl --user stop summitflow-terminal.service || true

echo ""
echo "Services stopped."
echo ""
