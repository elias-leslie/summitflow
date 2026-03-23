#!/bin/bash
#
# Restart a project. Delegates to rebuild.sh.
# Agent Hub's protected agent worker is only restarted when you pass
# --include-all-workers through to rebuild.sh.
# Usage: restart.sh <project>
#
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/rebuild.sh" "$@"
