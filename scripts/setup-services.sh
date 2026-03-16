#!/bin/bash
# SummitFlow Service Setup Script
# RUN THIS AS YOUR USER (with sudo prompts when needed)
#
# This script:
# 1. Symlinks systemd user services
# 2. Enables systemd user services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_DIR="$(dirname "$SCRIPT_DIR")"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "================================"
echo "SummitFlow Service Setup"
echo "================================"
echo ""
echo "SummitFlow directory: $SUMMITFLOW_DIR"
echo "User systemd dir: $USER_SYSTEMD_DIR"
echo ""

# Step 1: Create user systemd directory if needed
echo "Step 1: Setting up systemd user services..."
mkdir -p "$USER_SYSTEMD_DIR"

# Step 2: Create symlinks for all service files found in scripts/systemd/
echo "  Creating symlinks..."
SERVICES_LINKED=0
for svc_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.service; do
    [ -f "$svc_file" ] || continue
    svc_name="$(basename "$svc_file")"
    ln -sf "$svc_file" "$USER_SYSTEMD_DIR/$svc_name"
    echo "    $svc_name"
    SERVICES_LINKED=$((SERVICES_LINKED + 1))
done
echo "  Linked $SERVICES_LINKED service files"

# Step 3: Reload systemd user daemon
echo "  Reloading systemd user daemon..."
systemctl --user daemon-reload

# Step 4: Enable services
echo "  Enabling services..."
for svc_file in "$SUMMITFLOW_DIR"/scripts/systemd/*.service; do
    [ -f "$svc_file" ] || continue
    svc_name="$(basename "$svc_file")"
    systemctl --user enable "$svc_name" 2>/dev/null && echo "    enabled $svc_name" || echo "    skipped $svc_name (may require dependencies)"
done

echo "  ✓ Systemd services configured"
echo ""

echo "================================"
echo "✓ Setup complete!"
echo "================================"
echo ""
echo "To start SummitFlow services:"
echo "  bash ~/summitflow/scripts/start.sh"
echo ""
echo "To check status:"
echo "  bash ~/summitflow/scripts/status.sh"
echo ""
echo "Access URLs:"
echo "  - Local Backend:  http://localhost:8001"
echo "  - Local Frontend: http://localhost:3001"
echo ""
