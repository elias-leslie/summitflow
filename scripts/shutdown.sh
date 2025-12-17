#!/bin/bash
# Stop all SummitFlow services via systemd (User Mode)

echo "================================"
echo "Stopping SummitFlow Platform"
echo "================================"
echo ""

echo "Stopping frontend..."
systemctl --user stop summitflow-frontend.service 2>/dev/null || true

echo "Stopping backend..."
systemctl --user stop summitflow-backend.service 2>/dev/null || true

# Clean up any zombie processes
pkill -9 -f "summitflow/frontend.*next dev" 2>/dev/null || true
pkill -9 -f "summitflow/backend.*uvicorn" 2>/dev/null || true

echo ""
echo "✓ All SummitFlow services stopped"
echo ""
