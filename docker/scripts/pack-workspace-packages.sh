#!/bin/bash
# Pack workspace packages for Docker builds.
#
# JavaScript: @agent-hub/{chat-ui,push-client,passport-client} → .tgz tarballs
# Python: agent-hub-client → .whl wheel
#
# Docker builds are isolated, so workspace:* and local path deps won't resolve.
# This pre-packs everything so Dockerfiles can install from local artifacts.
#
# Steps per JS package:
# 1. Build (tsup → dist/)
# 2. pnpm pack → .tgz (may exclude dist/ due to root .gitignore)
# 3. Inject dist/ into tarball if missing
# 4. Patch exports: src/*.ts → dist/*.js (turbopack can't transpile .ts from node_modules)
# 5. Fix workspace: protocol deps → version strings
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SUMMITFLOW_ROOT_OVERRIDE="$SUMMITFLOW_ROOT"
. "$SUMMITFLOW_ROOT/scripts/lib/project-roots.sh"

OUT_DIR="${1:-/tmp/workspace-packages}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

AGENT_HUB_ROOT="${AGENT_HUB_ROOT:-$(resolve_project_root agent-hub)}"
PACKAGES_DIR="${AGENT_HUB_PACKAGES:-$AGENT_HUB_ROOT/packages}"

remove_dir() {
  python - "$1" <<'PY'
import pathlib
import shutil
import sys

path = pathlib.Path(sys.argv[1])
if path.exists():
    shutil.rmtree(path)
PY
}

pack_js_package() {
  local label="$1"
  local pkg_dir="$2"
  local tgz_name="$3"

  if [ ! -d "$pkg_dir" ]; then
    echo "SKIP: $pkg_dir not found"
    return
  fi

  echo "Packing $label..."

  # 1. Build
  (cd "$pkg_dir" && pnpm run build 2>&1 | tail -3)

  # 2. Pack
  (cd "$pkg_dir" && pnpm pack --pack-destination "$OUT_DIR")

  # 3-5. Patch tarball
  local tgz="$OUT_DIR/$tgz_name"
  if [ -f "$tgz" ]; then
    local tmp_dir
    tmp_dir=$(mktemp -d)
    tar xzf "$tgz" -C "$tmp_dir"

    # 3. Inject dist/ if not already in tarball
    if [ ! -d "$tmp_dir/package/dist" ] && [ -d "$pkg_dir/dist" ]; then
      cp -r "$pkg_dir/dist" "$tmp_dir/package/dist"
      echo "  Injected dist/"
    fi

    # 4-5. Patch package.json
    node -e "
      const fs = require('fs');
      const path = '$tmp_dir/package/package.json';
      const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));

      // Patch exports: src/*.ts → dist/*.js
      if (pkg.exports) {
        const str = JSON.stringify(pkg.exports);
        const patched = str
          .replace(/\"\.\/src\/([^\"]+)\.ts\"/g, (_, p) => '\"./dist/' + p + '.js\"')
          .replace(/\"\.\/src\/([^\"]+)\.tsx\"/g, (_, p) => '\"./dist/' + p + '.js\"');
        pkg.exports = JSON.parse(patched);
      }

      // Fix workspace: protocol deps → plain version
      for (const [dep, ver] of Object.entries(pkg.dependencies || {})) {
        if (typeof ver === 'string' && ver.startsWith('workspace:')) {
          pkg.dependencies[dep] = '0.1.0';
        }
      }

      fs.writeFileSync(path, JSON.stringify(pkg, null, 2));
    "

    # Repack
    (cd "$tmp_dir" && tar czf "$tgz" package/)
    remove_dir "$tmp_dir"
    echo "  Patched"
  fi
}

# ── JavaScript packages ──────────────────────────────────────────
for pkg in chat-ui push-client passport-client; do
  pack_js_package "@agent-hub/$pkg" "$PACKAGES_DIR/$pkg" "agent-hub-$pkg-0.1.0.tgz"
done

pack_js_package "@summitflow/notes-ui" "$SUMMITFLOW_ROOT/packages/notes-ui" "summitflow-notes-ui-0.1.0.tgz"

# ── Python package (uv build → .whl) ────────────────────────────
PYTHON_PKG="$PACKAGES_DIR/agent-hub-client"
if [ -d "$PYTHON_PKG" ]; then
  echo "Building agent-hub-client wheel..."
  (cd "$PYTHON_PKG" && uv build --wheel --out-dir "$OUT_DIR" 2>&1)
else
  echo "SKIP: $PYTHON_PKG not found"
fi

echo ""
echo "Packed workspace packages to $OUT_DIR:"
ls -lh "$OUT_DIR"/*.tgz "$OUT_DIR"/*.whl 2>/dev/null || echo "  (none)"
