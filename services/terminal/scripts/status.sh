#!/bin/bash
# Check Terminal service status

echo "================================"
echo "Terminal Service Status"
echo "================================"
echo ""

echo "Service Status (User Mode):"
echo "  Backend:  $(systemctl --user is-active summitflow-terminal.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo "  Frontend: $(systemctl --user is-active summitflow-terminal-frontend.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo ""

echo "Port Status:"
echo "  Backend:  $(ss -tlnp 2>/dev/null | grep -q ':8002' && echo 'Port 8002 bound' || echo 'Port 8002 not bound')"
echo "  Frontend: $(ss -tlnp 2>/dev/null | grep -q ':3002' && echo 'Port 3002 bound' || echo 'Port 3002 not bound')"
echo ""

echo "Health Check:"
BACKEND_HEALTH=$(curl -s http://localhost:8002/health 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unreachable")
echo "  Backend:  $BACKEND_HEALTH"
echo ""

echo "URLs:"
echo "  Local Backend:  http://localhost:8002"
echo "  Local Frontend: http://localhost:3002"
echo "  Production:     https://terminal.summitflow.dev"
echo ""
