#!/bin/bash
# SummitFlow Service Setup Script
# RUN THIS AS YOUR USER (with sudo prompts when needed)
#
# This script:
# 1. Symlinks systemd user services
# 2. Enables systemd user services
# 3. Installs nginx config (requires sudo)
# 4. Reloads nginx (requires sudo)

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

# Step 2: Create symlinks for service files
echo "  Creating symlinks..."
ln -sf "$SUMMITFLOW_DIR/scripts/systemd/summitflow-backend.service" "$USER_SYSTEMD_DIR/summitflow-backend.service"
ln -sf "$SUMMITFLOW_DIR/scripts/systemd/summitflow-frontend.service" "$USER_SYSTEMD_DIR/summitflow-frontend.service"

# Step 3: Reload systemd user daemon
echo "  Reloading systemd user daemon..."
systemctl --user daemon-reload

# Step 4: Enable services
echo "  Enabling services..."
systemctl --user enable summitflow-backend.service
systemctl --user enable summitflow-frontend.service

echo "  ✓ Systemd services configured"
echo ""

# Step 5: Install nginx config (requires sudo)
echo "Step 2: Installing nginx configuration..."
echo "  (This requires sudo access)"

if [ -f /etc/nginx/sites-available/summitflow ]; then
    echo "  Nginx config already exists, backing up..."
    sudo cp /etc/nginx/sites-available/summitflow /etc/nginx/sites-available/summitflow.bak
fi

sudo cp "$SUMMITFLOW_DIR/scripts/nginx/summitflow.conf" /etc/nginx/sites-available/summitflow

# Step 6: Enable nginx site
if [ ! -L /etc/nginx/sites-enabled/summitflow ]; then
    echo "  Enabling nginx site..."
    sudo ln -sf /etc/nginx/sites-available/summitflow /etc/nginx/sites-enabled/summitflow
fi

# Step 7: Test nginx config
echo "  Testing nginx configuration..."
sudo nginx -t

# Step 8: Reload nginx
echo "  Reloading nginx..."
sudo systemctl reload nginx

echo "  ✓ Nginx configured"
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
echo "  - HTTPS:          https://localhost:444"
echo ""
