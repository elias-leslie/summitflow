#!/bin/bash
#
# Check SummitFlow service status.
# Delegates to rebuild.sh --status (auto-detects Docker vs native).
#
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/rebuild.sh" --status "$@"
