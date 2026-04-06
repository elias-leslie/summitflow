#!/bin/bash
# Start the A-Term backend service

set -e

echo "Starting A-Term backend service..."
systemctl --user start a-term-backend.service
systemctl --user status a-term-backend.service --no-pager
echo "A-Term backend started on port 8002"
