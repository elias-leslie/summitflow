#!/bin/bash
# Stop the SummitFlow Terminal service

set -e

echo "Stopping SummitFlow Terminal service..."
systemctl --user stop summitflow-terminal.service
echo "Terminal service stopped"
