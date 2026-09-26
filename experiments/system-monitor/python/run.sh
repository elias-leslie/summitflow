#!/usr/bin/env bash
set -euo pipefail
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec "$root_dir/backend/.venv/bin/python" -B "$root_dir/experiments/system-monitor/python/collector.py" "$@"
