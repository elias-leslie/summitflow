#!/bin/bash
# Start the A-Term backend service

set -e

echo "Starting A-Term backend service..."
systemctl --user start aterm-backend.service
systemctl --user status aterm-backend.service --no-pager
echo "A-Term backend started on port 8002"
