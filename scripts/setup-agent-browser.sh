#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-latest}"
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
MANAGED_ROOT="${HOME}/.local/share/agent-browser-managed"
BIN_DIR="${HOME}/.local/bin"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
WRAPPER_SRC="${SCRIPT_DIR}/agent-browser-wrapper.js"
CANONICAL_SF_BROWSER_SRC="${SCRIPT_DIR}/sf-browser"
REAPER_SRC="${SCRIPT_DIR}/agent-browser-idle-reaper.js"
SERVICE_SRC="${SCRIPT_DIR}/systemd/agent-browser-idle-reaper.service"
TIMER_SRC="${SCRIPT_DIR}/systemd/agent-browser-idle-reaper.timer"
LEGACY_SKILL_DIR="${HOME}/.claude/skills/agent-browser"

mkdir -p "${MANAGED_ROOT}" "${BIN_DIR}" "${USER_UNIT_DIR}"

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

render_unit_file() {
  local src="$1"
  local dest="$2"
  local escaped_root
  escaped_root="$(escape_sed_replacement "$(dirname "${SCRIPT_DIR}")")"
  sed "s|__SUMMITFLOW_ROOT__|${escaped_root}|g" "$src" > "$dest"
}

prune_legacy_skill_bundle() {
  if [[ ! -d "${LEGACY_SKILL_DIR}" ]]; then
    return
  fi

  local shim_target
  shim_target="$(readlink -f "${BIN_DIR}/agent-browser" 2>/dev/null || true)"
  if [[ "${shim_target}" != "${WRAPPER_SRC}" ]]; then
    return
  fi

  rm -rf "${LEGACY_SKILL_DIR}/node_modules"
  rm -f "${LEGACY_SKILL_DIR}/package-lock.json"
  rm -f "${LEGACY_SKILL_DIR}/package.json"
  rm -f "${LEGACY_SKILL_DIR}/cloudflare-auth.js"
  rm -rf "${LEGACY_SKILL_DIR}/lib"
}

if [[ ! -f "${MANAGED_ROOT}/package.json" ]]; then
  cat > "${MANAGED_ROOT}/package.json" <<'EOF'
{
  "name": "agent-browser-managed",
  "version": "1.0.0",
  "private": true,
  "type": "commonjs"
}
EOF
fi

cd "${MANAGED_ROOT}"
npm install "agent-browser@${VERSION}"

ln -sfnT "${WRAPPER_SRC}" "${BIN_DIR}/agent-browser"
ln -sfnT "${CANONICAL_SF_BROWSER_SRC}" "${BIN_DIR}/sf-browser"
rm -f "${BIN_DIR}/browse"
chmod +x "${WRAPPER_SRC}" "${CANONICAL_SF_BROWSER_SRC}" "${REAPER_SRC}"

render_unit_file "${SERVICE_SRC}" "${USER_UNIT_DIR}/agent-browser-idle-reaper.service"
cp "${TIMER_SRC}" "${USER_UNIT_DIR}/agent-browser-idle-reaper.timer"

systemctl --user daemon-reload
systemctl --user enable agent-browser-idle-reaper.timer >/dev/null
systemctl --user restart agent-browser-idle-reaper.timer

prune_legacy_skill_bundle

echo "agent-browser wrapper: ${BIN_DIR}/agent-browser"
echo "sf-browser wrapper: ${BIN_DIR}/sf-browser"
echo "agent-browser package: $(node -p "require('${MANAGED_ROOT}/node_modules/agent-browser/package.json').version")"
