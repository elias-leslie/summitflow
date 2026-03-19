#!/bin/bash
#
# Restart a project. Delegates to rebuild.sh (which always does full rebuild).
# Usage: restart.sh <project>
#
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/rebuild.sh" "$@"
