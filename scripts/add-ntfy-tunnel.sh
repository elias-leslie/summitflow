#!/bin/bash
# Add ntfy.summitflow.dev route to Cloudflare tunnel
# Run with: sudo bash ~/summitflow/scripts/add-ntfy-tunnel.sh

set -euo pipefail

CONFIG="/etc/cloudflared/config.yml"

# Check if route already exists
if grep -q "ntfy.summitflow.dev" "$CONFIG"; then
    echo "[SKIP] ntfy.summitflow.dev route already exists in $CONFIG"
else
    # Insert before the test environments comment (or before catch-all)
    if grep -q "# Test environments" "$CONFIG"; then
        sed -i '/# Test environments/i\  # ntfy push notification server\n  - hostname: ntfy.summitflow.dev\n    service: http://localhost:2586' "$CONFIG"
    else
        # Insert before the catch-all 404 rule
        sed -i '/http_status:404/i\  # ntfy push notification server\n  - hostname: ntfy.summitflow.dev\n    service: http://localhost:2586' "$CONFIG"
    fi
    echo "[OK] Added ntfy.summitflow.dev route to $CONFIG"
fi

echo ""
echo "Current ingress rules:"
grep -E "hostname:|service:" "$CONFIG" | tail -20
echo ""

echo "Restarting cloudflared to pick up new route..."
systemctl restart cloudflared
sleep 2

if systemctl is-active --quiet cloudflared; then
    echo "[OK] cloudflared restarted successfully"
else
    echo "[FAIL] cloudflared failed to restart. Check: journalctl -u cloudflared -n 20"
    exit 1
fi

echo ""
echo "=== Next steps ==="
echo "1. In Cloudflare dashboard, create a CNAME DNS record:"
echo "   ntfy.summitflow.dev -> <tunnel-id>.cfargotunnel.com"
echo "   (Or use 'cloudflared tunnel route dns <tunnel-name> ntfy.summitflow.dev')"
echo ""
echo "2. Add ntfy.summitflow.dev to your existing CF Access Application"
echo "   with a Service Auth policy (use existing service token)"
