#!/bin/bash
# Start the SummitFlow Terminal service

set -e

echo "Starting SummitFlow Terminal service..."
systemctl --user start summitflow-terminal.service
systemctl --user status summitflow-terminal.service --no-pager
echo "Terminal service started on port 8002"
