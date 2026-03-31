#!/usr/bin/env bash
# System security updates - requires sudo
# Generated 2026-03-31 after vulnerability audit
set -euo pipefail

echo "=== System Security Updates ==="
echo ""

echo "[1/3] Updating Docker CE (29.3.0 -> 29.3.1)..."
sudo apt-get update -qq
sudo apt-get install -y --only-upgrade \
  docker-ce \
  docker-ce-cli \
  docker-ce-rootless-extras \
  docker-compose-plugin \
  docker-model-plugin

echo ""
echo "[2/3] Updating Node.js (24.14.0 -> 24.14.1)..."
sudo apt-get install -y --only-upgrade nodejs

echo ""
echo "[3/3] Applying coreutils security update..."
sudo apt-get install -y --only-upgrade \
  coreutils \
  ubuntu-drivers-common

echo ""
echo "=== Verifying ==="
docker --version
node --version
echo ""
echo "System security updates complete."
