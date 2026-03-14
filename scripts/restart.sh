#!/bin/bash
# Restart all SummitFlow services via systemd (User Mode)

set -e

START_TIME=$(date +%s)
log_time() {
    local NOW=$(date +%s)
    local ELAPSED=$((NOW - START_TIME))
    echo "[${ELAPSED}s] $1"
}

echo "================================"
echo "Restarting SummitFlow Platform"
echo "================================"
echo ""

log_time "Cleaning up zombie processes..."
pkill -9 -f "summitflow/frontend.*next dev" 2>/dev/null || true

log_time "Restarting backend..."
systemctl --user restart summitflow-backend.service

log_time "Restarting hatchet worker..."
systemctl --user restart summitflow-hatchet-worker.service

log_time "Restarting frontend..."
systemctl --user restart summitflow-frontend.service

log_time "Waiting for backend health..."
for i in {1..10}; do
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        log_time "Backend ready"
        break
    fi
    sleep 1
done

log_time "Waiting for frontend port..."
for i in {1..15}; do
    if ss -tlnp | grep -q ':3001'; then
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
echo "  Backend:      $(systemctl --user is-active summitflow-backend.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo "  Hatchet:      $(systemctl --user is-active summitflow-hatchet-worker.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo "  Frontend:     $(systemctl --user is-active summitflow-frontend.service 2>/dev/null && echo 'Running' || echo 'Stopped')"
echo ""
echo "Port Status:"
echo "  Backend:      $(ss -tlnp 2>/dev/null | grep -q ':8001' && echo 'Port 8001' || echo 'Port 8001 not bound')"
echo "  Frontend:     $(ss -tlnp 2>/dev/null | grep -q ':3001' && echo 'Port 3001' || echo 'Port 3001 not bound')"
echo ""
echo "URLs:"
echo "  Local Backend:  http://localhost:8001"
echo "  Local Frontend: http://localhost:3001"
echo ""
echo "Logs (via journalctl):"
echo "  Backend:  journalctl --user -u summitflow-backend -f"
echo "  Worker:   journalctl --user -u summitflow-hatchet-worker -f"
echo "  Frontend: journalctl --user -u summitflow-frontend -f"
echo ""
