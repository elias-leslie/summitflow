#!/bin/bash
# Stop the A-Term backend service

set -e

echo "Stopping A-Term backend service..."
systemctl --user stop aterm-backend.service
echo "A-Term backend stopped"
