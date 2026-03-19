#!/bin/bash
#
# Check summitflow service status.
#
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/rebuild.sh" --status summitflow "$@"
