#!/bin/bash
# Rebuild frontend with cache clearing and verification
set -e

cd "$(dirname "$0")/../frontend"

# Get old ETag for comparison
OLD_ETAG=$(curl -sI http://localhost:3001/ 2>/dev/null | grep -i etag | tr -d '\r' || echo "none")

echo "Clearing Next.js cache..."
rm -rf .next/cache

echo "Building..."
pnpm build

echo "Restarting service..."
systemctl --user restart summitflow-frontend
sleep 2

# Verify ETag changed
NEW_ETAG=$(curl -sI http://localhost:3001/ 2>/dev/null | grep -i etag | tr -d '\r' || echo "none")

if [[ "$OLD_ETAG" == "$NEW_ETAG" ]]; then
    echo "WARNING: ETag unchanged - cache may not have cleared"
    exit 1
fi

echo "OK: Frontend rebuilt (ETag changed)"
