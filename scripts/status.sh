#!/bin/bash
#
# Check summitflow service status.
#
set -eo pipefail
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
exec bash "$SCRIPT_DIR/rebuild.sh" --status summitflow "$@"
