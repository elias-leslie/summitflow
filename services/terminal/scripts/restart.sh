#!/bin/bash
# Restart Terminal services via systemd (User Mode)

set -e

START_TIME=$(date +%s)
log_time() {
    local NOW=$(date +%s)
    local ELAPSED=$((NOW - START_TIME))
    echo "[${ELAPSED}s] $1"
}

echo "================================"
echo "Restarting Terminal Service"
echo "================================"
echo ""

log_time "Restarting terminal backend..."
systemctl --user restart summitflow-terminal.service

log_time "Restarting terminal frontend..."
systemctl --user restart summitflow-terminal-frontend.service

log_time "Waiting for backend health..."
for i in {1..10}; do
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        log_time "Backend ready"
        break
    fi
    sleep 1
done

log_time "Waiting for frontend port..."
for i in {1..15}; do
    if ss -tlnp | grep -q ':3002'; then
        log_time "Frontend ready"
        break
    fi
    sleep 1
done

# Check status
echo ""
echo "================================"
echo "Restart complete!"
echo "================================"
echo ""
echo "Service Status (User Mode):"
echo "  Backend:  $(systemctl --user is-active summitflow-terminal.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo "  Frontend: $(systemctl --user is-active summitflow-terminal-frontend.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo ""
echo "Port Status:"
echo "  Backend:  $(ss -tlnp 2>/dev/null | grep -q ':8002' && echo 'Port 8002' || echo 'Port 8002 not bound')"
echo "  Frontend: $(ss -tlnp 2>/dev/null | grep -q ':3002' && echo 'Port 3002' || echo 'Port 3002 not bound')"
echo ""
echo "URLs:"
echo "  Local Backend:  http://localhost:8002"
echo "  Local Frontend: http://localhost:3002"
echo "  Production:     https://terminal.summitflow.dev"
echo ""
echo "Logs:"
echo "  Backend:  journalctl --user -u summitflow-terminal -f"
echo "  Frontend: journalctl --user -u summitflow-terminal-frontend -f"
echo ""
