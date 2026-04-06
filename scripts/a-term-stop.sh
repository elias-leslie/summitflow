#!/bin/bash
# Stop the A-Term backend service

set -e

echo "Stopping A-Term backend service..."
systemctl --user stop a-term-backend.service
echo "A-Term backend stopped"
