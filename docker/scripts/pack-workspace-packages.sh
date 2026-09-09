#!/bin/bash
# Pack workspace packages for Docker builds.
#
# JavaScript: @agent-hub/{chat-ui,passport-client} → .tgz tarballs
# Python: agent-hub-client → .whl wheel
#
# Docker builds are isolated, so workspace:* and local path deps won't resolve.
# This pre-packs everything so Dockerfiles can install from local artifacts.
#
# Package manifests own published exports/files. pnpm pack resolves workspace dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SUMMITFLOW_ROOT_OVERRIDE="$SUMMITFLOW_ROOT"
. "$SUMMITFLOW_ROOT/scripts/lib/project-roots.sh"

OUT_DIR="${1:-/tmp/workspace-packages}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

AGENT_HUB_ROOT="${AGENT_HUB_ROOT:-}"
if [ -z "$AGENT_HUB_ROOT" ]; then
  AGENT_HUB_ROOT="$(resolve_project_root agent-hub 2>/dev/null || true)"
fi
PACKAGES_DIR="${AGENT_HUB_PACKAGES:-}"
if [ -z "$PACKAGES_DIR" ] && [ -n "$AGENT_HUB_ROOT" ]; then
  PACKAGES_DIR="$AGENT_HUB_ROOT/packages"
fi

workspace_root_for() {
  local dir
  dir="$(cd "$1" && pwd)"

  while [ "$dir" != "/" ]; do
    if [ -f "$dir/pnpm-workspace.yaml" ] || [ -f "$dir/pnpm-lock.yaml" ]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done

  return 1
}

pack_js_package() {
  local label="$1"
  local pkg_dir="$2"
  local workspace_root=""

  if [ ! -d "$pkg_dir" ]; then
    echo "SKIP: $pkg_dir not found"
    return
  fi

  echo "Packing $label..."

  if [ ! -d "$pkg_dir/node_modules" ]; then
    echo "  Installing package dependencies..."
    workspace_root="$(workspace_root_for "$pkg_dir" || true)"
    if [ -n "$workspace_root" ] && [ -f "$workspace_root/pnpm-workspace.yaml" ]; then
      (cd "$workspace_root" && pnpm --filter "$label" install --frozen-lockfile)
    else
      (cd "$pkg_dir" && pnpm install --frozen-lockfile)
    fi
  fi

  (cd "$pkg_dir" && pnpm pack --pack-destination "$OUT_DIR")
}

# ── JavaScript packages ──────────────────────────────────────────
if [ -n "$PACKAGES_DIR" ]; then
  for pkg in passport-client chat-ui; do
    pack_js_package "@agent-hub/$pkg" "$PACKAGES_DIR/$pkg"
  done
else
  echo "SKIP: agent-hub packages root not found"
fi

pack_js_package "@summitflow/notes-ui" "$SUMMITFLOW_ROOT/packages/notes-ui"

# ── Python package (uv build → .whl) ────────────────────────────
PYTHON_PKG="${PACKAGES_DIR:+$PACKAGES_DIR/agent-hub-client}"
if [ -n "$PYTHON_PKG" ] && [ -d "$PYTHON_PKG" ]; then
  echo "Building agent-hub-client wheel..."
  (cd "$PYTHON_PKG" && SOURCE_DATE_EPOCH=1577836800 uv build --wheel --out-dir "$OUT_DIR" 2>&1)
else
  echo "SKIP: agent-hub-client package root not found"
fi

echo ""
echo "Packed workspace packages to $OUT_DIR:"
ls -lh "$OUT_DIR"/*.tgz "$OUT_DIR"/*.whl 2>/dev/null || echo "  (none)"
