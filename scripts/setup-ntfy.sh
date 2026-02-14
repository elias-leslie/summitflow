#!/bin/bash
# Setup ntfy as a user service for SummitFlow push notifications
# Run with: bash ~/summitflow/scripts/setup-ntfy.sh
# (NO sudo needed — runs as user service like all other SummitFlow services)

set -euo pipefail

NTFY_CONFIG="$HOME/.config/ntfy/server.yml"
NTFY_DATA="$HOME/.local/share/ntfy"
NTFY_CACHE="$HOME/.cache/ntfy"

echo "=== Setting up ntfy (user service) for SummitFlow ==="

# 1. Stop and disable system-level ntfy if running
if systemctl is-active --quiet ntfy 2>/dev/null; then
    echo "[INFO] System-level ntfy is running. Stop it with:"
    echo "  sudo systemctl stop ntfy && sudo systemctl disable ntfy"
    echo ""
    read -p "Have you stopped the system service? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Please stop the system service first, then re-run this script."
        exit 1
    fi
fi

# 2. Ensure directories exist
mkdir -p "$(dirname "$NTFY_CONFIG")" "$NTFY_DATA" "$NTFY_CACHE"
echo "[OK] Directories created"

# 3. Check config exists (should already be written by Claude)
if [[ ! -f "$NTFY_CONFIG" ]]; then
    echo "[FAIL] Config not found at $NTFY_CONFIG"
    exit 1
fi
echo "[OK] Config found at $NTFY_CONFIG"

# 4. Enable and start user service
systemctl --user daemon-reload
systemctl --user enable ntfy
systemctl --user start ntfy
echo "[OK] ntfy user service enabled and started"

# 5. Verify it's running
sleep 2
if systemctl --user is-active --quiet ntfy; then
    echo "[OK] ntfy is running on port 2586 (user service)"
else
    echo "[FAIL] ntfy failed to start. Check: journalctl --user -u ntfy -n 20"
    exit 1
fi

# 6. Setup auth — user commands use the same config automatically
echo ""
echo "=== Setting up authentication ==="

export NTFY_CONFIG_FILE="$NTFY_CONFIG"

# Create phone user for subscriptions (read-only on sf-alerts)
NTFY_PASSWORD=phone123 ntfy user add --ignore-exists phone
echo "[OK] User 'phone' created (or already exists)"

ntfy access phone 'sf-alerts' ro
echo "[OK] Read-only access granted to phone on sf-alerts"

# Allow anonymous write on sf-alerts (SummitFlow backend posts to localhost)
ntfy access '*' 'sf-alerts' wo
echo "[OK] Anonymous write access granted on sf-alerts"

# Generate a token for the phone
echo ""
echo "=== Phone subscription token ==="
ntfy token add phone
echo ""
echo "Save this token ^^^ — you'll enter it in the ntfy Android app."

echo ""
echo "=== Quick test ==="
curl -s -d "ntfy user service setup complete" http://localhost:2586/sf-alerts | python3 -m json.tool
echo ""
echo "=== Done! ==="
echo ""
echo "View logs: journalctl --user -u ntfy -f"
echo "Status:    systemctl --user status ntfy"
